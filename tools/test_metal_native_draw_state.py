#!/usr/bin/env python3
"""Verify the live CPU draw packer against immutable original game inputs.

No graphics context: raw D3D arrays produce the original shader key/uniforms
and the proven native wire state. --ilp32 builds and executes those same126
comparisons with the actual rebased guest pointer/long ABI.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.metal_shader_validate import PixelKey
from tools.metal_draw_replay import split_uniforms, texture_description
from tools.metal_host_draw_validate import state_bytes, sampler_bytes

FRAME = ROOT/'build/metal-reference-20261004/ordered-frame-runtime/run/saves/metal-frames/frame420/captured_frame.json'
PREPARED = ROOT/'build/metal-poc/frame-replay-420-sample-mask/frame-replay.json'
FRAME_SHA = '75f256ed7d40324d24cfb754e93248699defdcdc89d3f60d271dc9482ff115ac'
ENUM_NAMES = ('D3DBLEND','D3DBLENDOP','D3DCMPFUNC','D3DCULL','D3DFILLMODE','D3DFOGMODE','D3DFORMAT',
              'D3DFRONT','D3DRENDERSTATETYPE','D3DSTENCILOP','D3DTEXTUREADDRESS',
              'D3DTEXTUREALPHAKILL','D3DTEXTUREFILTERTYPE','D3DTEXTURESTAGESTATETYPE')
U32, F32 = C.c_uint32, C.c_float
TexRow, Constants = U32*32, (F32*4)*192

class Texture(C.Structure):
    _fields_ = [(name,U32) for name in ('present','sampler_type','width','height','levels','linear','hires','hires_coverage')]

class Input(C.Structure):
    _fields_ = [('render_state',C.POINTER(U32)),('texture_state',C.POINTER(TexRow)),
                ('constants',C.POINTER(F32*4)),('viewport_scale',C.POINTER(F32)),
                ('viewport_offset',C.POINTER(F32)),('viewport',F32*6),
                ('target_width',U32),('target_height',U32),('has_depth',U32),
                ('sample_count',U32),('screen_offset',C.c_int32),('textures',Texture*4),
                ('native_black_border',U32),('native_alpha_border',U32),
                ('texture_depth',U32*4),('native_volume',U32),('native_depth_contract',U32),
                ('original_auto_depth_format',U32),('depth_surface_format_word',U32),
                ('floating_point_zbuffer',U32),('native_volume_border',U32)]

class Output(C.Structure):
    _fields_ = [('vertex',F32*780),('pixel',F32*152),('state',U32*38),
                ('samplers',U32*40),('active_texture_mask',U32),('native_alpha_border_mask',U32),
                ('depth_contract',U32),('native_volume_border_mask',U32)]

DEPTH_CAPTURE = ROOT/'build/macos-metal/live-depth-diagnostic/dumps'
DEPTH_CAPTURE_HASHES = {
    'original-depth-metadata':'d7b72a012a40557c84057f8d273b0299472270c79033034f2d8b99cbcb00e9f4',
    'pixel-key':'f13524b388b542bc2c4d328e9df265e6acd4265df92dd2916b0d89a52067d0aa',
    'vertex-words':'cfa2422d0176a22fa85fc0b1e175a3a604868560851606896d8601d8da6fbe46',
    'vertex-constants':'16933be669ce6125e844eff1c589ddeb19e1ecb5894afdfad8d7e05a96d01930',
    'viewport-scale-offset':'c973f4eece7082fdd198908299959305b7e0b8d0e27923cdda3be461031cd6c5',
    'viewport':'1941a14faa2f30f5ec594ea0d8f5d05e460e0ae1c7e354780293b1bf44396dbf',
}

CAMPAIGN_CAPTURE = ROOT/'build/macos-metal/campaign-failure-diagnostic-attempt2'
CAMPAIGN_CONSTANTS = (
    ('d20',73,'6d68ed5ebfacdc3dd0d628623e8bc878ef4592570f376cf19ebaabd7e16fb82c'),
    ('d40',510,'eeb0edd88295a2630089a7c4fa5481643ee99e3c9d9a8d35ab2285bd5dd1ae2c'),
)
CAMPAIGN_VERTEX_SHA = '2406f0323b5435ac02be40c7325166bd96c4d8a8361ccc90c9ba2ba4e58aae50'
RAW_CONSTANT_PATTERNS = (0x7f800000,0xff800000,0x7fc12345,0xffc12345,
                         0x7fa12345,0xffa12345,0xffffffff,0x80000000)

def campaign_constant_inputs():
    """Actual failed banks/VS9, not invented NaN values or sanitized fixtures."""
    result=[]
    for name,frame,expected in CAMPAIGN_CONSTANTS:
        folder=CAMPAIGN_CAPTURE/name/'dumps'
        constants=folder/f'native-failure-frame{frame}-vertex-constants.bin'
        words=folder/f'native-failure-frame{frame}-vertex-words.bin'
        if not constants.exists() or not words.exists():
            raise unittest.SkipTest('immutable d20/d40 failure captures required')
        assert sha(constants)==expected and sha(words)==CAMPAIGN_VERTEX_SHA
        raw=constants.read_bytes()
        assert len(raw)==3072 and struct.unpack_from('<I',raw,23*16+12)[0]==0xffffffff
        result.append((name,raw))
    return result

def raw_constant_case(name, raw, original=None):
    """Keep captured original draw0 state; replace only its raw constant bank.

    Campaign variants use actual d20/d40 constant bytes. Unrelated state and
    resources remain draw0 CPU controls, not a complete campaign GPU replay.
    """
    assert len(raw)==3072
    if original is None:original=captured_cases()[0]
    data=Input.from_buffer_copy(bytes(original[1]))
    constants=Constants.from_buffer_copy(raw);data.constants=constants
    expected=raw+original[3][3072:]
    keep=(*original[4][:2],constants,*original[4][3:])
    return name,data,original[2],expected,keep

def depth_capture():
    result={}
    for name,expected in DEPTH_CAPTURE_HASHES.items():
        path=DEPTH_CAPTURE/f'native-program-frame89-{name}.bin'
        if not path.exists():raise unittest.SkipTest('authoritative live integer-D24 capture required')
        assert sha(path)==expected, 'Original live depth input changed: '+name
        result[name]=path.read_bytes()
    metadata=struct.unpack('<6I',result['original-depth-metadata'])
    assert metadata[:4]==(1,0,42,0x2e21) and metadata[4]==0x271df27f and metadata[5]!=0
    assert struct.unpack('<4I2f',result['viewport'])==(0,0,640,480,0,1)
    assert struct.unpack('<8f',result['viewport-scale-offset'])==(320,-240,16777215,0,320,240,0,0)
    assert struct.unpack_from('<2f',result['vertex-constants'],33*16)==(16778240,-1048640)
    return result

class Error(C.Structure):
    _fields_ = [('stage',U32),('state',U32),('value',U32),('message',C.c_char_p)]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def prefix():
    # Read enum values from the checked-in original XDK declarations. Suppress
    # only the full OS platform include, using its exact guest scalar types.
    xdk = (ROOT/'port/include/xdk/xdk_pdb.h').read_text()
    result = '''#include <stdint.h>
#define __HALO_LINUX_PLATFORM_H
#define HALO_MACOS_NATIVE_METAL 1
typedef uint32_t DWORD;
typedef uint32_t D3DCOLOR;
typedef int BOOL;
#define TRUE 1
#define FALSE 0
'''
    for name in ENUM_NAMES:
        result += re.search(r'enum _'+name+r'\s*\{.*?\};',xdk,re.S).group(0)+'\n'
    return result

def canonical_key(key):
    data = struct.pack('<58I',*key.combiner_state,key.texture_modes)
    for name in ('sampler_type','alpha_kill','color_sign','border_axes','border_filter'):
        data += bytes(getattr(key,name))
    return data + struct.pack('<I4B',key.alpha_test_function,key.fog_enable,
                              key.fog_table_mode,key.count_samples,key.coverage_alpha) + bytes(key.custom_edition_channels)

def key_from_json(data):
    key = PixelKey()
    for name,_ in PixelKey._fields_:
        if name in data:
            if isinstance(data[name],list):getattr(key,name)[:] = data[name]
            else:setattr(key,name,data[name])
    return key

def payload(root, desc):
    data = (root/desc['file']).read_bytes()
    assert len(data) == desc.get('bytes',desc.get('size'))
    assert hashlib.sha256(data).hexdigest() == desc['sha256']
    return data

def captured_cases():
    if not FRAME.exists() or not PREPARED.exists():
        raise unittest.SkipTest('immutable original frame420 and prepared replay are required')
    assert sha(FRAME) == FRAME_SHA, 'Original captured frame identity changed'
    frame, manifest = json.loads(FRAME.read_text()), json.loads(PREPARED.read_text())
    assert manifest['source_capture']['sha256'] == FRAME_SHA
    corpus = (FRAME.parent/frame['shader_corpus']).resolve()
    targets = {t['target_id']:t for t in frame['targets'].values() if t['version']==0}
    cases = []
    for name,draw in frame['draws'].items():
        normalized = manifest['draws'][name]
        uniforms = payload(FRAME.parent,draw['draw_uniforms'])
        constants = payload(FRAME.parent,draw['vertex_constants'])
        rs = (U32*144).from_buffer_copy(payload(FRAME.parent,draw['render_state_words']))
        ts = (TexRow*4).from_buffer_copy(payload(FRAME.parent,draw['texture_state_words']))
        const = Constants.from_buffer_copy(constants)
        scale = (F32*4).from_buffer_copy(uniforms[:16])
        offset = (F32*4).from_buffer_copy(uniforms[16:32])
        vp = draw['viewport']
        target = targets[draw['before']['color']['target_id']]
        input_data = Input(rs,ts,const,scale,offset,
            (F32*6)(*draw['actual_gl_viewport'],vp['znear'],vp['zfar']),
            target['width'],target['height'],int(draw['before'].get('depth_stencil') is not None),
            1,int(struct.unpack_from('<f',uniforms,616)[0]))
        for slot,texture in enumerate(draw['textures']):
            if texture:
                description = texture_description(texture['format_word'],texture['size_word'])
                input_data.textures[slot] = Texture(1,3 if description['cube_map'] else 2 if texture['depth']>1 else 1,
                    texture['width'],texture['height'],texture['levels'],int(description['linear']),0,0)
        key_file = corpus/f'pixel-{draw["pixel_id"]:04d}.json'
        assert sha(key_file) == frame['shader_corpus_sha256'][key_file.name]
        expected_key = canonical_key(key_from_json(json.loads(key_file.read_text())))
        vertex,pixel = split_uniforms(constants,uniforms)
        expected_samplers = b''
        mask=0
        for slot,binding in enumerate(normalized['textures']):
            if binding and binding['type'] != 'unbound_passthrough':
                expected_samplers += sampler_bytes(binding['sampler']);mask |= 1<<slot
            else:expected_samplers += bytes(40)
        expected = vertex+pixel+state_bytes(normalized['render_state'])+expected_samplers+struct.pack('<4I',mask,0,0,0)
        assert len(expected)==C.sizeof(Output)==4056
        # Retain backing arrays: C input holds their pointers, not ownership.
        cases.append((name,input_data,expected_key,expected,(rs,ts,const,scale,offset)))
    assert len(cases)==126
    return cases

def captured_depth_case(bounded=False, dependent_ar=False):
    """Captured key/depth/constants with explicit fixture-only sampler state.

    The diagnostic did not capture all textures/render arrays. Unrelated
    arrays retain immutable draw0, and three known 2D repeat samplers isolate
    CPU packing. This is not a complete actual zsprite GPU draw package.
    """
    raw=depth_capture();original=captured_cases()[0]
    data=Input.from_buffer_copy(bytes(original[1]))
    rs=(U32*144).from_buffer_copy(bytes(original[4][0]));ts=(TexRow*4)()
    rs[:57]=struct.unpack_from('<57I',raw['pixel-key'])
    rs[116]=struct.unpack_from('<I',raw['pixel-key'],228)[0]
    rs[60]=0;rs[82]=1;rs[83]=0
    constants=Constants.from_buffer_copy(raw['vertex-constants'])
    scale=(F32*4).from_buffer_copy(raw['viewport-scale-offset'][:16])
    offset=(F32*4).from_buffer_copy(raw['viewport-scale-offset'][16:])
    x,y,width,height,near,far=struct.unpack('<4I2f',raw['viewport'])
    if bounded:
        near,far=.25,.75
        scale[2]=16777215*(far-near);offset[2]=16777215*near
    data.render_state=rs;data.texture_state=ts;data.constants=constants
    data.viewport_scale=scale;data.viewport_offset=offset
    data.viewport[:]=(x,y,width,height,near,far);data.has_depth=1
    data.native_depth_contract=1
    _,data.floating_point_zbuffer,data.original_auto_depth_format,data.depth_surface_format_word,_,_=struct.unpack('<6I',raw['original-depth-metadata'])
    for stage in range(4):
        data.textures[stage]=Texture(1,1,4,4,1,0,0,0)
        ts[stage][10]=ts[stage][11]=ts[stage][12]=1
        ts[stage][13]=ts[stage][14]=ts[stage][18]=1
    expected=bytearray(original[3])
    expected[:3072]=raw['vertex-constants']
    expected[3072:3104]=bytes(scale)+bytes(offset)
    expected[3120:3408]=bytes(288) # captured key's constants are zero
    struct.pack_into('<3f',expected,3120+324,1/16777215,near,far)
    expected[3120+336:3120+464]=bytes(128)
    struct.pack_into('<16f',expected,3120+464,*([1.]*16))
    expected[3120+528:3728]=bytes(80)
    expected[3880:4040]=bytes(160)
    sampler=struct.pack('<8I2f',0,0,0,0,0,0,1,0,0,0)
    for stage in (0,1,3):expected[3880+stage*40:3920+stage*40]=sampler
    struct.pack_into('<6f4I',expected,3728+80,x,y,width,height,near,far,x,y,width,height)
    struct.pack_into('<III',expected,4040,11,0,1)
    expected_key=bytearray(raw['pixel-key'])+bytearray(4)
    if dependent_ar:
        #0x0f is a sampled dependent AR read, not depth replacement. Its
        # default-zero depth metadata must not trigger the D24-only gate.
        rs[116]=1|(15<<5);data.native_depth_contract=0
        data.original_auto_depth_format=data.depth_surface_format_word=data.floating_point_zbuffer=0
        struct.pack_into('<I',expected_key,228,rs[116]);expected_key[234:236]=bytes(2)
        expected[3120+324:3120+336]=bytes(12)
        expected[3880+120:4040]=bytes(40)
        struct.pack_into('<III',expected,4040,3,0,0)
    name='dependent-ar-default' if dependent_ar else 'captured-d24-bounded' if bounded else 'captured-d24-live-metadata'
    return name,data,bytes(expected_key),bytes(expected),(rs,ts,constants,scale,offset)

def depth_negative_cases():
    mutations=[('opt-out','native_depth_contract',0,-2,'DOT_ZW'),
        ('unknown-contract','native_depth_contract',2,-2,'depth contract'),
        ('no-depth','has_depth',0,-2,'DOT_ZW'),
        ('float-Z','floating_point_zbuffer',1,-2,'DOT_ZW'),
        ('malformed-float-Z','floating_point_zbuffer',2,-2,'DOT_ZW'),
        ('missing-request','original_auto_depth_format',0,-2,'DOT_ZW'),
        ('missing-surface','depth_surface_format_word',0,-2,'DOT_ZW'),
        ('D16-scale','scale-2',65535,-2,'D24'),
        ('F24-scale','scale-2',1e30,-2,'D24'),
        ('wrong-offset','offset-2',.125,-2,'D24')]
    for fmt in (43,47,44,48,45,49):
        mutations.append((f'request-format-{fmt}','original_auto_depth_format',fmt,-2,'DOT_ZW'))
        mutations.append((f'surface-format-{fmt}','depth_surface_format_word',(fmt<<8)|0x21,-2,'DOT_ZW'))
    for index,value in ((4,-.25),(5,1.25),(4,1.25),(5,-.25)):
        mutations.append((f'viewport-{index}-{value}',f'viewport-{index}',value,-2,'depth range'))
    for index,value in ((4,float('nan')),(5,float('inf'))):
        mutations.append((f'viewport-nonfinite-{index}',f'viewport-{index}',value,-1,'nonfinite'))
    result=[]
    for name,field,value,status,phrase in mutations:
        _,data,_key,_expected,keep=captured_depth_case()
        if field.startswith('viewport-'):data.viewport[int(field[-1])]=value
        elif field.startswith('scale-'):data.viewport_scale[int(field[-1])]=value
        elif field.startswith('offset-'):data.viewport_offset[int(field[-1])]=value
        else:setattr(data,field,value)
        result.append((name,data,status,phrase,keep))
    return result

def ilp32_cases():
    cases=captured_cases()
    # Two independent wire expectations cover the new opt-in in the actual
    # guest ABI as well. Other fields retain an immutable original baseline;
    # source operands/key constants are not invented to match GPU results.
    for anisotropy in (1,8):
        original=cases[0];data=Input.from_buffer_copy(bytes(original[1]))
        rs=(U32*144).from_buffer_copy(bytes(original[4][0]))
        ts=(TexRow*4).from_buffer_copy(bytes(original[4][1]))
        data.render_state=rs;data.texture_state=ts;data.native_black_border=1
        data.textures[0]=Texture(1,1,32,32,6,0,0,0)
        rs[116]=(rs[116]&~31)|1
        ts[0][10]=ts[0][11]=4;ts[0][12]=1
        ts[0][13]=2;ts[0][14]=3 if anisotropy>1 else 2;ts[0][15]=2
        ts[0][17]=0;ts[0][18]=anisotropy;ts[0][29]=0
        key=bytearray(original[2]);struct.pack_into('<I',key,228,rs[116])
        key[232]=1;key[244]=key[248]=0
        expected=bytearray(original[3]);struct.pack_into('<4f',expected,3120+464,1,1,1,1)
        expected[3120+528:3120+544]=bytes(16)
        struct.pack_into('<8I2f',expected,3880,1,1,2,3,3,0,anisotropy,0,0,5)
        mask=struct.unpack_from('<I',expected,4040)[0]|1;struct.pack_into('<I',expected,4040,mask)
        keep=(rs,ts,*original[4][2:])
        cases.append((f'new-black-border-anisotropy-{anisotropy}',data,bytes(key),bytes(expected),keep))
    for axis,border in ((3,0x46000000),(1,0xff000000)):
        original=cases[0];data=Input.from_buffer_copy(bytes(original[1]))
        rs=(U32*144).from_buffer_copy(bytes(original[4][0]))
        ts=(TexRow*4).from_buffer_copy(bytes(original[4][1]))
        data.render_state=rs;data.texture_state=ts;data.native_alpha_border=1
        data.textures[0]=Texture(1,1,64,64,5,0,0,0)
        rs[116]=(rs[116]&~31)|1
        ts[0][10]=4;ts[0][11]=4 if axis==3 else 2;ts[0][12]=1
        ts[0][13]=ts[0][14]=2;ts[0][15]=1
        ts[0][17]=0;ts[0][18]=1;ts[0][29]=border
        key=bytearray(original[2]);struct.pack_into('<I',key,228,rs[116])
        key[232]=1;key[244]=key[248]=0
        expected=bytearray(original[3]);struct.pack_into('<4f',expected,3120+464,1,1,1,1)
        struct.pack_into('<4f',expected,3120+528,0,0,0,(border>>24)/255)
        struct.pack_into('<8I2f',expected,3880,1,1,1,3,3 if axis==3 else 1,0,1,0,0,4)
        mask=struct.unpack_from('<I',expected,4040)[0]|1;struct.pack_into('<II',expected,4040,mask,1)
        cases.append((f'new-alpha-border-axes-{axis}',data,bytes(key),bytes(expected),(rs,ts,*original[4][2:])))
    for stage,width,height,min_filter,mip_filter in ((0,32,32,1,1),(2,4,2,1,1),(1,32,32,2,2)):
        original=cases[0];data=Input.from_buffer_copy(bytes(original[1]))
        rs=(U32*144).from_buffer_copy(bytes(original[4][0]))
        ts=(TexRow*4).from_buffer_copy(bytes(original[4][1]))
        data.render_state=rs;data.texture_state=ts;data.native_volume=data.native_black_border=1
        data.texture_depth[stage]=32;data.textures[stage]=Texture(1,2,width,height,6,0,0,0)
        rs[116]=(rs[116]&~(31<<(5*stage)))|(2<<(5*stage))
        ts[stage][10]=ts[stage][11]=ts[stage][12]=4
        ts[stage][13]=2;ts[stage][14]=min_filter;ts[stage][15]=mip_filter
        ts[stage][17]=0;ts[stage][18]=1;ts[stage][29]=0
        key=bytearray(original[2]);struct.pack_into('<I',key,228,rs[116])
        key[232+stage]=2;key[244+stage]=key[248+stage]=0
        expected=bytearray(original[3]);struct.pack_into('<4f',expected,3120+464+16*stage,1,1,1,1)
        expected[3120+528+16*stage:3120+544+16*stage]=bytes(16)
        struct.pack_into('<8I2f',expected,3880+40*stage,min_filter-1,1,mip_filter,3,3,3,1,0,0,5)
        mask=struct.unpack_from('<I',expected,4040)[0]|(1<<stage);struct.pack_into('<I',expected,4040,mask)
        cases.append((f'new-volume-stage-{stage}',data,bytes(key),bytes(expected),(rs,ts,*original[4][2:])))
    cases.extend((captured_depth_case(),captured_depth_case(bounded=True),
                  captured_depth_case(dependent_ar=True)))
    return cases

def volume_color_case(stage=1, linear=True, axes=7, border=0x05050505, alpha_stage=None):
    """Independent expected CPU bytes for the authored-RGBA 3D contract.

    The actual startup border/filter/dimensions are represented; shaders and
    unrelated render state remain explicit immutable-baseline CPU fixtures.
    """
    original=captured_cases()[0];data=Input.from_buffer_copy(bytes(original[1]))
    rs=(U32*144).from_buffer_copy(bytes(original[4][0]))
    ts=(TexRow*4).from_buffer_copy(bytes(original[4][1]))
    data.render_state=rs;data.texture_state=ts
    data.native_volume=data.native_volume_border=1;data.texture_depth[stage]=32
    data.textures[stage]=Texture(1,2,32,32,6,0,0,0)
    rs[116]=(rs[116]&~(31<<(5*stage)))|(2<<(5*stage))
    row=ts[stage]
    row[10:13]=tuple(4 if axes&(1<<i) else (1,2,3)[i] for i in range(3))
    row[13]=2;row[14]=row[15]=2 if linear else 1
    row[17]=0;row[18]=1;row[29]=border
    key=bytearray(original[2]);struct.pack_into('<I',key,228,rs[116])
    key[232+stage]=2;key[244+stage]=key[248+stage]=0
    expected=bytearray(original[3]);struct.pack_into('<4f',expected,3120+464+stage*16,1,1,1,1)
    rgba=tuple(((border>>shift)&255)/255 for shift in (16,8,0,24))
    struct.pack_into('<4f',expected,3120+528+stage*16,*rgba)
    addresses=tuple(3 if axes&(1<<i) else (0,1,2)[i] for i in range(3))
    struct.pack_into('<8I2f',expected,3880+stage*40,int(linear),1,2 if linear else 1,*addresses,1,0,0,5)
    struct.pack_into('<I',expected,4040,struct.unpack_from('<I',expected,4040)[0]|(1<<stage))
    struct.pack_into('<I',expected,4052,1<<stage)
    if alpha_stage is not None:
        assert alpha_stage!=stage
        data.native_alpha_border=1;data.textures[alpha_stage]=Texture(1,1,64,64,5,0,0,0)
        rs[116]=(rs[116]&~(31<<(5*alpha_stage)))|(1<<(5*alpha_stage))
        row=ts[alpha_stage];row[10]=row[11]=4;row[12]=1
        row[13]=row[14]=2;row[15]=1;row[17]=0;row[18]=1;row[29]=0x46000000
        struct.pack_into('<I',key,228,rs[116]);key[232+alpha_stage]=1
        key[244+alpha_stage]=key[248+alpha_stage]=0
        struct.pack_into('<4f',expected,3120+464+alpha_stage*16,1,1,1,1)
        struct.pack_into('<4f',expected,3120+528+alpha_stage*16,0,0,0,70/255)
        struct.pack_into('<8I2f',expected,3880+alpha_stage*40,1,1,1,3,3,0,1,0,0,4)
        struct.pack_into('<II',expected,4040,struct.unpack_from('<I',expected,4040)[0]|(1<<alpha_stage),1<<alpha_stage)
    return 'volume-color-stage-'+str(stage),data,bytes(key),bytes(expected),(rs,ts,*original[4][2:])

def volume_color_negative_cases():
    mutations=[('opt-out','native_volume_border',0),('unknown-contract','native_volume_border',2),
        ('volume-opt-out','native_volume',0),('one-mip','levels',1),('linear-coordinates','linear',1),
        ('hires','hires',1),('min-point','min',1),('mag-point','mag',1),('mip-point','mip',1),
        ('aniso','aniso',2)]
    result=[]
    for name,field,value in mutations:
        _,data,_key,_expected,keep=volume_color_case()
        if field in ('native_volume_border','native_volume'):setattr(data,field,value)
        elif field in ('levels','linear','hires'):setattr(data.textures[1],field,value)
        else:keep[1][1][{'min':14,'mag':13,'mip':15,'aniso':18}[field]]=value
        result.append(('volume-color-'+name,data,-2,'volume',keep))
    return result

class DrawStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('clang'):raise unittest.SkipTest('clang required')
        cls.temp=tempfile.TemporaryDirectory(prefix='halo-native-state-')
        cls.directory=Path(cls.temp.name)
        pref=cls.directory/'prefix.h';pref.write_text(prefix())
        cls.library=cls.directory/'draw-state.dylib'
        subprocess.run(['clang','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
            '-include',pref,ROOT/'port/linux/src/metal_draw_state.c','-o',cls.library],check=True,capture_output=True)
        cls.lib=C.CDLL(str(cls.library))
        cls.lib.metal_draw_state_pack.argtypes=[C.POINTER(Input),C.POINTER(PixelKey),C.POINTER(Output),C.POINTER(Error)]
        cls.lib.metal_draw_state_pack.restype=C.c_int

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def basic(self):
        rs=(U32*144)();ts=(TexRow*4)();constants=Constants()
        rs[57]=515;rs[58]=519;rs[62]=1;rs[63]=0;rs[67]=0x01010101
        rs[68]=rs[69]=rs[125]=7680;rs[70]=519;rs[72]=rs[73]=255
        rs[74]=32774;rs[119]=6914;rs[123]=1;rs[126]=2304
        scale=(F32*4)(320,-240,1,1);offset=(F32*4)(320,240,0,0)
        data=Input(rs,ts,constants,scale,offset,(F32*6)(13,7,320,240,0,1),640,480,1,1,0)
        return data,(rs,ts,constants,scale,offset)

    def run_pack(self,data):
        key=PixelKey();out=Output();error=Error()
        status=self.lib.metal_draw_state_pack(C.byref(data),C.byref(key),C.byref(out),C.byref(error))
        return status,key,out,error

    def reject_atomic(self,data,status,phrase):
        key=PixelKey();out=Output();error=Error()
        C.memset(C.byref(key),0xa7,C.sizeof(key));C.memset(C.byref(out),0x53,C.sizeof(out))
        self.assertEqual(self.lib.metal_draw_state_pack(C.byref(data),C.byref(key),C.byref(out),C.byref(error)),status)
        self.assertEqual(bytes(key),bytes([0xa7])*C.sizeof(key));self.assertEqual(bytes(out),bytes([0x53])*C.sizeof(out))
        self.assertIn(phrase,error.message.decode())

    def test_no_gl_imports(self):
        self.assertNotRegex(subprocess.check_output(['nm','-u',self.library],text=True),r'\b_(?:gl[A-Z]|host_gl_|hud_hires_)')

    def test_all126_original_keys_uniforms_and_wire_state(self):
        for name,data,expected_key,expected,_keep in captured_cases():
            with self.subTest(draw=name):
                status,key,out,error=self.run_pack(data)
                self.assertEqual(status,0,error.message)
                self.assertEqual(canonical_key(key),expected_key,'original captured shader key')
                for label,start,end in (('VS',0,3120),('PS',3120,3728),('draw state',3728,3880),('samplers',3880,4040),('binding mask',4040,4044),('alpha border mask',4044,4048)):
                    self.assertEqual(bytes(out)[start:end],expected[start:end],label)
                self.assertEqual(out.depth_contract,0)
                self.assertEqual(out.native_volume_border_mask,0)

    def test_actual_campaign_constant_padding_is_retained(self):
        for name,raw in campaign_constant_inputs():
            with self.subTest(map=name):
                _,data,expected_key,expected,keep=raw_constant_case(name,raw)
                before=(bytes(data),tuple(bytes(array) for array in keep))
                status,key,out,error=self.run_pack(data)
                self.assertEqual(status,0,error.message)
                self.assertEqual(canonical_key(key),expected_key)
                self.assertEqual(bytes(out),expected)
                self.assertEqual(bytes(out.vertex)[23*16+12:23*16+16],b'\xff'*4)
                self.assertEqual((bytes(data),tuple(bytes(array) for array in keep)),before)

    def test_raw_constant_payloads_are_preserved_in_every_component(self):
        data,keep=self.basic()
        status,expected_key,expected_out,error=self.run_pack(data)
        self.assertEqual(status,0,error.message)
        constant_words=C.cast(C.addressof(keep[2]),C.POINTER(U32))
        for component in range(192*4):
            for payload_bits in RAW_CONSTANT_PATTERNS:
                with self.subTest(register=component//4,component=component%4,bits=hex(payload_bits)):
                    constant_words[component]=payload_bits
                    before=(bytes(data),tuple(bytes(array) for array in keep))
                    expected=bytearray(bytes(expected_out))
                    struct.pack_into('<I',expected,component*4,payload_bits)
                    status,key,out,error=self.run_pack(data)
                    self.assertEqual(status,0,error.message)
                    self.assertEqual(bytes(key),bytes(expected_key))
                    self.assertEqual(bytes(out),bytes(expected))
                    self.assertEqual((bytes(data),tuple(bytes(array) for array in keep)),before)
            constant_words[component]=0

    def test_nonfinite_viewport_components_still_reject_atomically(self):
        for field,length in (('viewport',6),('viewport_scale',4),('viewport_offset',4)):
            for component in range(length):
                for bits in RAW_CONSTANT_PATTERNS[:-1]:
                    with self.subTest(field=field,component=component,bits=hex(bits)):
                        data,keep=self.basic()
                        array=data.viewport if field=='viewport' else keep[3 if field=='viewport_scale' else 4]
                        C.cast(C.addressof(array),C.POINTER(U32))[component]=bits
                        before=(bytes(data),tuple(bytes(array) for array in keep))
                        self.reject_atomic(data,-1,'nonfinite')
                        self.assertEqual((bytes(data),tuple(bytes(array) for array in keep)),before)

    def test_captured_integer_d24_contract_and_bounded_viewport(self):
        for case in (captured_depth_case(),captured_depth_case(bounded=True)):
            name,data,expected_key,expected,_keep=case
            with self.subTest(case=name):
                status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
                self.assertEqual(canonical_key(key),expected_key)
                self.assertEqual(bytes(out),expected)
                self.assertEqual(out.depth_contract,1)
                self.assertEqual(list(out.pixel)[81:84],
                    [C.c_float(1/16777215).value,data.viewport[4],data.viewport[5]])

    def test_integer_d24_unverified_units_and_viewport_reject_atomically(self):
        for name,data,status,phrase,_keep in depth_negative_cases():
            with self.subTest(case=name):self.reject_atomic(data,status,phrase)

    def test_dependent_ar_is_not_depth_replacement(self):
        _name,data,expected_key,expected,_keep=captured_depth_case(dependent_ar=True)
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(canonical_key(key),expected_key);self.assertEqual(bytes(out),expected)
        self.assertEqual(key.sampler_type[1],1);self.assertEqual(out.active_texture_mask,3)
        self.assertEqual(out.depth_contract,0);self.assertEqual(list(out.pixel)[81:84],[0,0,0])

    def test_ordinary_opt_in_retains_default_output_and_zero_depth(self):
        data,keep=self.basic();status,key,expected,error=self.run_pack(data)
        self.assertEqual(status,0,error.message)
        data.native_depth_contract=1;data.original_auto_depth_format=42
        data.depth_surface_format_word=0x2e21;data.floating_point_zbuffer=0
        status,again,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(bytes(out),bytes(expected));self.assertEqual(bytes(again),bytes(key))
        self.assertEqual(out.depth_contract,0);self.assertEqual(list(out.pixel)[81:84],[0,0,0])

    def test_constants_alpha_sign_and_bump_order(self):
        data,keep=self.basic();rs,ts,constants,_,_=keep
        rs[10]=0x7f1b9cfe;rs[18]=0x80f10521;rs[43]=0x28192735;rs[44]=0xd1bc7039
        rs[60]=1;rs[58]=514;rs[61]=0x12ab;rs[82]=1;rs[83]=3
        rs[118]=0x37ea0193;rs[116]=1;rs[106]=struct.unpack('<I',struct.pack('<f',2.5))[0]
        for index,value in zip((22,23,25,24,26,27,16),(1.25,-2.5,3.75,-4.5,.25,.125,-.75)):
            ts[0][index]=struct.unpack('<I',struct.pack('<f',value))[0]
        ts[0][20]=0xd1234567;ts[0][21]=4;ts[0][29]=0x12345678
        ts[0][10]=ts[0][11]=ts[0][12]=1;ts[0][13]=ts[0][14]=2
        data.textures[0]=Texture(1,1,256,128,1,1,0,0)
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(list(key.combiner_state[10:26]),[0]*16)
        self.assertEqual((key.combiner_state[43],key.combiner_state[44]),(0,0))
        self.assertEqual((key.alpha_test_function,key.alpha_kill[0],key.color_sign[0],key.fog_enable,key.fog_table_mode),(514,1,13,1,3))
        self.assertEqual(struct.unpack_from('<4f',bytes(out.pixel),336),(1.25,-2.5,3.75,-4.5))
        self.assertEqual(struct.unpack_from('<4f',bytes(out.pixel),464),(1/256,1/128,1,1))
        self.assertEqual(out.vertex[776],2.5)
        self.assertEqual(out.pixel[80],171.)
        self.assertEqual(struct.unpack_from('<4f',bytes(out.pixel),592)[0],-.75)
        self.assertEqual(key.count_samples,0)

    def test_subviewport_scissor_front_cull_and_bias(self):
        data,keep=self.basic();rs=keep[0];rs[127]=2304;rs[81]=1
        rs[77]=0xc0000000;rs[78]=0xc1000000;rs[129]=8
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        raw=bytes(out.state)
        self.assertEqual(struct.unpack_from('<4I',raw,104),(13,7,320,240))
        self.assertEqual(out.state[16:20],[0,1,0,0])
        self.assertEqual(struct.unpack_from('<4f',raw,120),(-8,-2,0,0))
        rs[126]=2305
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.state[16:18],[1,2])
        data.has_depth=0
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.state[5:7],[0,0]);self.assertEqual(out.state[8],0)

    def test_blend_comparison_stencil_and_mask_enum_domains(self):
        data,keep=self.basic();rs=keep[0]
        factors=(0,1,768,769,770,771,772,773,774,775,776,32769,32770,32771,32772)
        for wire,original in enumerate(factors,1):
            rs[62]=original;rs[63]=original
            status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
            self.assertEqual(out.state[2:4],[wire,wire])
        for wire,original in enumerate((32774,32778,32779,32775,32776),1):
            rs[74]=original
            status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
            self.assertEqual(out.state[4],wire)
        for wire,original in enumerate(range(512,520),1):
            rs[57]=rs[70]=original
            status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
            self.assertEqual((out.state[7],out.state[9]),(wire,wire))
        for wire,original in enumerate((7680,0,7681,7682,7683,5386,34055,34056),1):
            rs[125]=rs[68]=rs[69]=original
            status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
            self.assertEqual(out.state[12:15],[wire]*3)
        for mask in range(16):
            rs[67]=(0x10000 if mask&1 else 0)|(0x100 if mask&2 else 0)|(1 if mask&4 else 0)|(0x1000000 if mask&8 else 0)
            status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
            self.assertEqual(out.state[0],mask)
        rs[57]=rs[70]=0
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual((out.state[7],out.state[9]),(1,1))

    def test_non_sampled_stages_do_not_bind_supplied_resources(self):
        data,keep=self.basic();rs,ts=keep[:2]
        for stage,mode in enumerate((0,4,5,17)):
            rs[116] |= mode<<(stage*5)
            data.textures[stage]=Texture(1,3,64,64,7,0,0,0)
            ts[stage][10]=99 # inactive sampler state is unconsumed
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(list(key.sampler_type),( [0,0,0,1]))
        self.assertEqual(bytes(out.samplers),bytes(160));self.assertEqual(out.active_texture_mask,0)
        self.assertEqual(list(out.pixel)[116:132],[1.]*16)

    def test_sampler_mips_and_resource_bounds(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,64,32,7,0,0,0)
        ts[0][10]=ts[0][11]=ts[0][12]=5
        ts[0][13]=2;ts[0][14]=3;ts[0][15]=1;ts[0][17]=3;ts[0][18]=8
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[:8],[1,1,1,2,2,2,8,0])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),32),(3,6))
        for index,value,phrase in ((13,4,'filter'),(15,3,'mip filter'),(10,6,'address'),(17,7,'minimum mip'),(18,17,'anisotropy')):
            old=ts[0][index];ts[0][index]=value
            self.reject_atomic(data,-2,phrase);ts[0][index]=old
        data.textures[0].levels=8
        self.reject_atomic(data,-2,'mip chain')
        data.textures[0]=Texture(1,3,64,32,1,0,0,0)
        self.reject_atomic(data,-2,'square')
        data.textures[0]=Texture(1,2,32,32,1,0,0,0)
        self.reject_atomic(data,-2,'volume')

    def test_border_and_unused_w_are_dimension_aware(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,64,32,1,0,0,0)
        ts[0][10]=4;ts[0][11]=2;ts[0][12]=4;ts[0][13]=1;ts[0][14]=2
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual((key.border_axes[0],key.border_filter[0]),(1,1))
        self.assertEqual(out.samplers[3:6],[2,1,2])
        data.textures[0].levels=2
        self.reject_atomic(data,-2,'border emulation')
        data.textures[0]=Texture(1,3,32,32,1,0,0,0)
        ts[0][10]=ts[0][11]=3
        self.reject_atomic(data,-2,'W border')

    def test_explicit_volume_preserves_xyz_key_mips_and_sampler(self):
        data,keep=self.basic();rs,ts=keep[:2];stage=2;rs[116]=2<<(5*stage)
        data.textures[stage]=Texture(1,2,32,32,6,0,0,0)
        data.texture_depth[stage]=32;data.native_volume=data.native_black_border=1
        ts[stage][10]=ts[stage][11]=ts[stage][12]=4
        ts[stage][13]=2;ts[stage][14]=ts[stage][15]=1;ts[stage][18]=1
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(key.sampler_type[stage],2)
        self.assertEqual((key.border_axes[stage],key.border_filter[stage]),(0,0))
        self.assertEqual(out.samplers[20:28],[0,1,1,3,3,3,1,0])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),112),(0,5))
        self.assertEqual(out.active_texture_mask,4);self.assertEqual(out.native_alpha_border_mask,0)
        self.assertEqual(struct.unpack_from('<4f',bytes(out.pixel),464+stage*16),(1,1,1,1))
        # Depth controls the last level for a genuinely noncubic volume.
        data.textures[stage].width=4;data.textures[stage].height=2
        self.assertEqual(self.run_pack(data)[0],0)

    def test_volume_unknown_metadata_and_border_are_atomic(self):
        for name,value,phrase in (('native_volume',0,'volume'),('depth',0,'volume'),
                                  ('depth',513,'volume'),('linear',1,'volume'),
                                  ('hires',1,'volume'),('levels',7,'mip chain'),
                                  ('native_black_border',0,'volume border'),('border',0x01000000,'volume border'),
                                  ('min',2,'volume border'),('mag',1,'volume border'),
                                  ('mip',2,'volume border'),('anisotropy',8,'volume border')):
            with self.subTest(field=name,value=value):
                data,keep=self.basic();rs,ts=keep[:2];rs[116]=2
                data.textures[0]=Texture(1,2,32,32,6,0,0,0)
                data.native_volume=data.native_black_border=1;data.texture_depth[0]=32
                ts[0][10]=ts[0][11]=ts[0][12]=4
                ts[0][13]=2;ts[0][14]=ts[0][15]=1;ts[0][18]=1
                if name in ('native_volume','native_black_border'):setattr(data,name,value)
                elif name=='depth':data.texture_depth[0]=value
                elif name in ('linear','hires','levels'):setattr(data.textures[0],name,value)
                else:ts[0][{'border':29,'min':14,'mag':13,'mip':15,'anisotropy':18}[name]]=value
                self.reject_atomic(data,-2,phrase)
        data,keep=self.basic();data.native_volume=2;self.reject_atomic(data,-2,'volume contract')

    def test_original_specular_all_linear_volume_border(self):
        data,keep=self.basic();rs,ts=keep[:2];stage=1;rs[116]=2<<(5*stage)
        data.textures[stage]=Texture(1,2,32,32,6,0,0,0)
        data.texture_depth[stage]=32;data.native_volume=data.native_black_border=1
        ts[stage][10]=ts[stage][11]=ts[stage][12]=4
        ts[stage][13]=ts[stage][14]=ts[stage][15]=2;ts[stage][18]=1
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(key.sampler_type[stage],2)
        self.assertEqual((key.border_axes[stage],key.border_filter[stage]),(0,0))
        self.assertEqual(out.samplers[10:18],[1,1,2,3,3,3,1,0])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),72),(0,5))
        self.assertEqual(out.native_alpha_border_mask,0)
        for index,value in ((13,1),(14,1),(15,1),(18,8),(29,0x01000000)):
            old=ts[stage][index];ts[stage][index]=value
            self.reject_atomic(data,-2,'volume border');ts[stage][index]=old

    def test_authored_rgba_volume_border_exact_stage_axes_and_footprints(self):
        for stage in range(4):
            for linear in (False,True):
                for axes in range(1,8):
                    for border in (0x05050505,0x7f12a6e3,0xff000000,0xffffffff):
                        with self.subTest(stage=stage,linear=linear,axes=axes,border=hex(border)):
                            _,data,expected_key,expected,_keep=volume_color_case(stage,linear,axes,border)
                            status,key,out,error=self.run_pack(data)
                            self.assertEqual(status,0,error.message)
                            self.assertEqual(canonical_key(key),expected_key)
                            self.assertEqual(bytes(out),expected)

    def test_authored_volume_and_alpha_masks_remain_disjoint(self):
        _,data,expected_key,expected,_keep=volume_color_case(alpha_stage=3)
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(canonical_key(key),expected_key);self.assertEqual(bytes(out),expected)
        self.assertEqual((out.native_volume_border_mask,out.native_alpha_border_mask),(2,8))
        data.native_black_border=1;_keep[1][1][29]=0
        self.assertEqual(self.run_pack(data)[2].native_volume_border_mask,0)

    def test_authored_volume_border_rejections_are_atomic(self):
        for name,data,status,phrase,_keep in volume_color_negative_cases():
            with self.subTest(case=name):self.reject_atomic(data,status,phrase)

    def test_hires_override_and_coverage_gate(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,512,512,3,0,1,1)
        ts[0][10]=ts[0][11]=ts[0][12]=1;ts[0][13]=ts[0][14]=1
        ts[0][15]=0;ts[0][17]=2;ts[0][16]=0x3f800000
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(key.coverage_alpha,0);self.assertEqual(out.samplers[:3],[1,1,2])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),32),(0,2))
        self.assertEqual(out.pixel[148],0.) # high-res HUD uses unbiased replacement mips
        rs[59]=1;rs[62]=32769;rs[63]=770
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(key.coverage_alpha,1)
        self.assertEqual(out.state[1:5],[1,12,5,1])

    def test_hires_coverage_is_stage0_and_original_meter_blend_only(self):
        for stage in range(4):
            for enabled,source,destination,coverage in ((1,32769,770,1),(0,32769,770,0),
                                                       (1,1,770,0),(1,32769,0,0)):
                with self.subTest(stage=stage,blend=(enabled,source,destination)):
                    data,keep=self.basic();rs,ts=keep[:2]
                    rs[116]=1<<(5*stage);rs[59]=enabled;rs[62]=source;rs[63]=destination
                    data.textures[stage]=Texture(1,1,64,32,7,0,1,1)
                    ts[stage][10]=ts[stage][11]=ts[stage][12]=1
                    ts[stage][13]=ts[stage][14]=1;ts[stage][17]=2
                    status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
                    self.assertEqual(key.coverage_alpha,coverage if stage==0 else 0)

    def test_hires_metadata_rejects_nonreplacement_coverage_and_cube(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,64,64,7,0,0,1)
        self.reject_atomic(data,-2,'coverage requires')
        data.textures[0]=Texture(1,3,64,64,7,0,1,1)
        self.reject_atomic(data,-2,'requires texture2d')

    def test_hires_alpha_border_uses_same_trilinear_footprint(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1;data.native_alpha_border=1
        data.textures[0]=Texture(1,1,512,512,10,0,1,0)
        ts[0][10]=ts[0][11]=4;ts[0][12]=1
        ts[0][13]=ts[0][14]=ts[0][15]=1;ts[0][18]=1;ts[0][29]=0x46000000
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[:8],[1,1,2,3,3,0,1,0])
        self.assertEqual((key.border_axes[0],key.border_filter[0],out.native_alpha_border_mask),(0,0,1))
        self.assertAlmostEqual(out.pixel[135],70/255)

    def test_explicit_native_black_border_six_mips_and_anisotropy(self):
        # Exact newly observed live draw state:32x32, six authored levels,
        # normalized2D, U/VBORDER/Wwrap, transparentblack, trilinear, aniso1.
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,32,32,6,0,0,0)
        ts[0][10]=ts[0][11]=4;ts[0][12]=1
        ts[0][13]=ts[0][14]=ts[0][15]=2;ts[0][18]=1;ts[0][29]=0
        self.reject_atomic(data,-2,'explicit native transparent-black')
        data.native_black_border=1
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[:8],[1,1,2,3,3,0,1,0])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),32),(0,5))
        self.assertEqual((key.border_axes[0],key.border_filter[0]),(0,0))
        self.assertEqual(bytes(out.pixel)[528:544],bytes(16))
        ts[0][14]=3;ts[0][18]=8
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[6],8)
        # Independent axis selection retains the original non-border mode.
        ts[0][11]=2
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[3:6],[3,1,0])
        ts[0][29]=0xff000000
        self.reject_atomic(data,-2,'explicit native transparent-black')
        ts[0][29]=0;data.textures[0].sampler_type=3
        self.reject_atomic(data,-2,'explicit native transparent-black')
        data.textures[0].sampler_type=1;data.native_black_border=2
        self.reject_atomic(data,-2,'unknown native black-border')

    def test_native_border_opt_in_preserves_single_level_shader_footprint(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,32,32,1,0,0,0)
        ts[0][10]=ts[0][11]=4;ts[0][12]=1;ts[0][13]=ts[0][14]=2
        ts[0][29]=0x46271953 # authored arbitrary alpha/color still emulated
        status,key,expected,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        data.native_black_border=1
        data.native_alpha_border=1
        status,new_key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(canonical_key(new_key),canonical_key(key));self.assertEqual(bytes(out),bytes(expected))
        self.assertEqual((key.border_axes[0],key.border_filter[0]),(3,3))

    def test_explicit_native_alpha_border_authored_mip_state(self):
        data,keep=self.basic();rs,ts=keep[:2];rs[116]=1
        data.textures[0]=Texture(1,1,64,64,5,0,0,0)
        ts[0][10]=ts[0][11]=4;ts[0][12]=1
        ts[0][13]=ts[0][14]=2;ts[0][15]=1;ts[0][18]=1;ts[0][29]=0x46000000
        self.reject_atomic(data,-2,'alpha-border')
        data.native_alpha_border=1
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[:8],[1,1,1,3,3,0,1,0])
        self.assertEqual(struct.unpack_from('<2f',bytes(out.samplers),32),(0,4))
        self.assertEqual((key.border_axes[0],key.border_filter[0],out.native_alpha_border_mask),(0,0,1))
        self.assertEqual(struct.unpack_from('<4f',bytes(out.pixel),528),(0,0,0,C.c_float(70/255).value))
        ts[0][11]=2
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.samplers[3:6],[3,1,0]);self.assertEqual(out.native_alpha_border_mask,1)
        # Every stage has a distinct typed companion bit/binding.
        for stage in range(1,4):
            rs[116]|=1<<(5*stage);data.textures[stage]=Texture(1,1,64,64,5,0,0,0)
            ts[stage][:]=ts[0][:]
        status,key,out,error=self.run_pack(data);self.assertEqual(status,0,error.message)
        self.assertEqual(out.native_alpha_border_mask,15)

    def test_native_alpha_border_unverified_footprints_reject_atomically(self):
        changes=[('RGB',lambda d,t:t[0].__setitem__(29,0x46000100)),
                 ('linear',lambda d,t:setattr(d.textures[0],'linear',1)),
                 ('cube',lambda d,t:setattr(d.textures[0],'sampler_type',3)),
                 ('trilinear',lambda d,t:t[0].__setitem__(15,2)),
                 ('point min',lambda d,t:t[0].__setitem__(14,1)),
                 ('point mag',lambda d,t:t[0].__setitem__(13,1)),
                 ('anisotropy',lambda d,t:t[0].__setitem__(18,2)),
                 ('anisotropic filter',lambda d,t:t[0].__setitem__(14,3))]
        for name,change in changes:
            with self.subTest(case=name):
                data,keep=self.basic();rs,ts=keep[:2];rs[116]=1;data.native_alpha_border=1
                data.textures[0]=Texture(1,1,64,64,5,0,0,0)
                ts[0][10]=ts[0][11]=4;ts[0][12]=1
                ts[0][13]=ts[0][14]=2;ts[0][15]=1;ts[0][18]=1;ts[0][29]=0x46000000
                change(data,ts);self.reject_atomic(data,-2,'alpha-border')
        data,keep=self.basic();data.native_alpha_border=2
        self.reject_atomic(data,-2,'unknown native alpha-border')

    def test_nonfinite_and_unsupported_are_atomic(self):
        cases=[('sample',lambda d,k:setattr(d,'sample_count',4),-2,'multisample'),
            ('W depth',lambda d,k:k[0].__setitem__(123,2),-2,'nonboolean'),
            ('logic blend',lambda d,k:k[0].__setitem__(74,61446),-2,'render state enum'),
            ('point fill',lambda d,k:k[0].__setitem__(119,6912),-2,'point fill'),
            ('DOT ZW',lambda d,k:k[0].__setitem__(116,10),-2,'DOT_ZW'),
            ('nan point size',lambda d,k:k[0].__setitem__(106,0x7fc12345),-1,'nonfinite'),
            ('nan bump',lambda d,k:k[1][3].__setitem__(27,0x7fc00000),-1,'nonfinite'),
            ('fractional viewport',lambda d,k:d.viewport.__setitem__(0,.25),-2,'rounded'),
            ('uint overflow',lambda d,k:d.viewport.__setitem__(0,4294967296),-2,'rounded')]
        for name,change,status,phrase in cases:
            with self.subTest(case=name):
                data,keep=self.basic();change(data,keep);self.reject_atomic(data,status,phrase)

def build_ilp32(output, plugin, executor, llvm=Path('/opt/homebrew/opt/llvm@22/bin'),
                linker=Path('/opt/homebrew/opt/lld@22/bin/ld.lld')):
    """Prepare a pure CPU guest proof. Does not initialize Metal or submit GPU work."""
    from tools.android_build import GUEST_ABI_FLAGS
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'prepared.json').exists():raise ValueError('Preserve existing proof; choose a fresh output folder')
    files=[Path(__file__),ROOT/'port/linux/src/metal_draw_state.c',ROOT/'port/linux/src/metal_draw_state.h',
           ROOT/'port/linux/src/xgpu.h',ROOT/'port/linux/src/platform.h',ROOT/'port/macos/include/halo_metal_abi.h',
           ROOT/'port/include/xdk/xdk_pdb.h',ROOT/'tools/android_build.py',ROOT/'tools/android_asm_convert.py',
           ROOT/'tools/android_imports.py',ROOT/'port/macos/metal_imports.list',
           ROOT/'tools/metal_draw_replay.py',ROOT/'tools/metal_host_draw_validate.py',
           ROOT/'tools/metal_shader_validate.py',FRAME,PREPARED,
           *[DEPTH_CAPTURE/f'native-program-frame89-{name}.bin' for name in DEPTH_CAPTURE_HASHES],
           *[CAMPAIGN_CAPTURE/name/'dumps'/f'native-failure-frame{frame}-{suffix}.bin'
             for name,frame,_ in CAMPAIGN_CONSTANTS for suffix in ('vertex-constants','vertex-words')]]
    before={str(path):sha(path) for path in files}
    source_root=output/'source-snapshot'
    for path in files:
        relative=path.resolve().relative_to(ROOT);destination=source_root/relative
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    # Freestanding standard declarations; the actual production module uses
    # only memcpy/memset and a compiler finite test, no system/GL/Metal calls.
    include=output/'freestanding';include.mkdir()
    (include/'math.h').write_text('#define isfinite(x) __builtin_isfinite(x)\n')
    (include/'string.h').write_text('void *memcpy(void *,const void *,unsigned long);\nvoid *memset(void *,int,unsigned long);\n')
    positive=ilp32_cases()+[volume_color_case(stage,linear,1+(stage*2),
                0x05050505 if linear else 0x7f12a6e3) for stage in range(4) for linear in (False,True)]
    positive.append(volume_color_case(alpha_stage=3))
    original=positive[0]
    positive.extend(raw_constant_case('actual-'+name+'-raw-bank',raw,original)
                    for name,raw in campaign_constant_inputs())
    positive.extend(raw_constant_case('all-components-raw-'+hex(bits),struct.pack('<768I',*([bits]*768)),original)
                    for bits in RAW_CONSTANT_PATTERNS)
    negative=depth_negative_cases()+volume_color_negative_cases()
    cases=[(name,data,0,expected_key,expected,keep) for name,data,expected_key,expected,keep in positive]
    cases += [(name,data,status,bytes([0xa7])*264,bytes([0x53])*4056,keep)
              for name,data,status,_phrase,keep in negative]
    blob=bytearray()
    for _name,data,status,expected_key,expected,keep in cases:
        rs,ts,const,scale,offset=keep
        blob += bytes(rs)+bytes(ts)+bytes(const)+bytes(scale)+bytes(offset)+bytes(data.viewport)
        blob += struct.pack('<4Ii',data.target_width,data.target_height,data.has_depth,data.sample_count,data.screen_offset)
        blob += bytes(data.textures)+struct.pack('<II4II',data.native_black_border,data.native_alpha_border,
            *data.texture_depth,data.native_volume)
        blob += struct.pack('<5Ii',data.native_depth_contract,data.original_auto_depth_format,
            data.depth_surface_format_word,data.floating_point_zbuffer,data.native_volume_border,status)+expected_key+expected
    assert len(positive)==155 and len(negative)==38 and len(blob)==len(cases)*(4412+4+264+4056)
    binary=output/'cases.bin';binary.write_bytes(blob)
    assembly=output/'cases.s'
    assembly.write_text('.section .rodata\n.balign 16\n.global draw_state_cases\ndraw_state_cases:\n.incbin "'+str(binary)+'"\n')
    source=output/'guest.c'
    source.write_text(prefix()+'''\n#include "'''+str(source_root/'port/linux/src/metal_draw_state.c')+'''"
_Static_assert(sizeof(void*)==4 && sizeof(unsigned long)==4, "real guest ILP32 ABI");
_Static_assert(sizeof(struct nv2a_pixel_shader_key)==264, "original guest key ABI");
struct case_input {
    uint32_t rs[144],ts[4][32]; float c[192][4],scale[4],offset[4],viewport[6];
    uint32_t width,height,has_depth,sample_count; int32_t screen_offset;
    struct metal_draw_texture textures[4];
    uint32_t native_black_border,native_alpha_border;
    uint32_t texture_depth[4],native_volume;
    uint32_t native_depth_contract,original_auto_depth_format,depth_surface_format_word,floating_point_zbuffer;
    uint32_t native_volume_border;
};
struct test_case { struct case_input input; int32_t expected_status; unsigned char expected_key[264],expected_output[4056]; };
_Static_assert(sizeof(struct case_input)==4412 && sizeof(struct test_case)==8732,"case blob ABI");
extern const struct test_case draw_state_cases['''+str(len(cases))+'''];
void *memcpy(void *destination,const void *source,unsigned long size) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(unsigned long i=0;i<size;i++)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,unsigned long size) {
    unsigned char *d=destination;for(unsigned long i=0;i<size;i++)d[i]=(unsigned char)value;return destination;
}
static int equal(const void *a,const void *b,uint32_t size) {
    const unsigned char *x=a,*y=b;for(uint32_t i=0;i<size;i++)if(x[i]!=y[i])return 0;return 1;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;
    for(uint32_t i=0;i<'''+str(len(cases))+''';i++) {
        const struct test_case *test=&draw_state_cases[i];const struct case_input *data=&test->input;
        struct metal_draw_state_input input={0};
        input.render_state=data->rs;input.texture_state=data->ts;input.constants=data->c;
        input.viewport_scale=data->scale;input.viewport_offset=data->offset;
        memcpy(input.viewport,data->viewport,24);input.target_width=data->width;input.target_height=data->height;
        input.has_depth=data->has_depth;input.sample_count=data->sample_count;input.screen_offset=data->screen_offset;
        memcpy(input.textures,data->textures,sizeof(input.textures));
        input.native_black_border=data->native_black_border;
        input.native_alpha_border=data->native_alpha_border;
        memcpy(input.texture_depth,data->texture_depth,16);input.native_volume=data->native_volume;
        input.native_depth_contract=data->native_depth_contract;
        input.original_auto_depth_format=data->original_auto_depth_format;
        input.depth_surface_format_word=data->depth_surface_format_word;
        input.floating_point_zbuffer=data->floating_point_zbuffer;
        input.native_volume_border=data->native_volume_border;
        struct nv2a_pixel_shader_key key;struct metal_draw_state_output out;struct metal_draw_state_error error;
        memset(&key,0xa7,sizeof(key));memset(&out,0x53,sizeof(out));memset(&error,0,sizeof(error));
        int status=metal_draw_state_pack(&input,&key,&out,&error);
        if(status!=test->expected_status)return 1000+i;
        if(!equal(&key,test->expected_key,264))return 2000+i;
        if(!equal(&out,test->expected_output,4056))return 3000+i;
        if(status && (!error.message || (error.stage!=UINT32_MAX && error.stage>3)))return 4000+i;
    }
    return 0;
}
''')
    def run(*args):
        result=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stderr or result.stdout)
    resource=Path(subprocess.check_output([str(llvm/'clang'),'-print-resource-dir'],text=True).strip())
    run(llvm/'clang',*GUEST_ABI_FLAGS,'-O2','-ffreestanding','-fno-builtin','-isystem',resource/'include',
        '-I',include,'-std=gnu11','-Wall','-Wextra','-Werror','-emit-llvm','-S',source,'-o',output/'guest.ll')
    run(llvm/'opt','-load-pass-plugin='+str(plugin),'-passes=halo-rebase,verify','-S',output/'guest.ll','-o',output/'guest.rebased.ll')
    run(llvm/'llc','-O2','-mtriple=arm64_32-apple-watchos','-aarch64-neon-syntax=generic',output/'guest.rebased.ll','-o',output/'guest.darwin.s')
    run(sys.executable,'tools/android_asm_convert.py',output/'guest.darwin.s',output/'guest.s')
    for name in ('guest','cases'):
        run(llvm/'clang','--target=aarch64-linux-android','-c',output/(name+'.s'),'-o',output/(name+'.o'))
    run(sys.executable,'tools/android_imports.py','--host-table',output/'host_import_table.c',output/'imports.s','port/macos/metal_imports.list')
    run(llvm/'clang','--target=aarch64-linux-android','-c',output/'imports.s','-o',output/'imports.o')
    script=output/'guest.ld';script.write_text('ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n')
    run(linker,'-m','aarch64elf','-T',script,output/'guest.o',output/'cases.o',output/'imports.o','-o',output/'guest.elf')
    symbols={}
    for line in subprocess.check_output([str(llvm/'llvm-nm'),'--defined-only',str(output/'guest.elf')],text=True).splitlines():
        fields=line.split()
        if len(fields)==3:symbols[fields[2]]=int(fields[0],16)
    copied_executor=output/'host_ilp32_probe';shutil.copy2(executor,copied_executor)
    command=[str(copied_executor),str(output/'guest.elf'),*[hex(symbols[name]) for name in
        ('__host_import_table','__host_import_names','__host_import_count')],'0x800000']
    assert before=={str(path):sha(path) for path in files}, 'Source changed during preparation'
    dependencies=[*output.glob('*.*'),*include.iterdir(),*source_root.rglob('*')]
    dependencies=[p for p in dependencies if p.is_file()]
    proof=dict(schema_version=1,kind='native_draw_state_ilp32_cpu',complete=False,passed=False,
        original_frame_sha256=FRAME_SHA,original_draw_count=126,synthetic_border_cases=4,synthetic_volume_cases=3,
        captured_depth_cpu_cases=2,dependent_ar_cases=1,atomic_depth_rejection_cases=28,
        synthetic_volume_color_cases=9,atomic_volume_color_rejection_cases=10,
        actual_campaign_raw_banks=2,all_components_raw_banks=len(RAW_CONSTANT_PATTERNS),
        total_cases=len(cases),compared_bytes_per_draw=4316,
        guest_pointer_bits=32,guest_long_bits=32,source_sha256=before,
        prepared_sha256={str(p):sha(p) for p in dependencies},executor_sha256=sha(copied_executor),
        toolchain_sha256={str(p):sha(p) for p in (plugin,llvm/'clang',llvm/'opt',llvm/'llc',linker)},
        execution_command=command,cases=[{'name':c[0],'expected_status':c[2]} for c in cases],
        limits=['CPU state packing only; no GPU work, presentation or gameplay proof',
                'depth capture supplies actual key/constants/target provenance; unrelated arrays/samplers are explicit CPU fixtures'])
    (output/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(dict(prepared=str(output/'prepared.json'),execution_command=command),indent=2))

def consume_ilp32(output, stdout, returncode):
    prepared_path=output/'prepared.json';proof=json.loads(prepared_path.read_text())
    for path,expected in proof['prepared_sha256'].items():
        assert sha(path)==expected, 'Stale CPU proof dependency: '+path
    assert sha(proof['execution_command'][0])==proof['executor_sha256']
    observed=json.loads(stdout.read_text())
    passed=returncode==0 and observed.get('passed') is True and observed.get('guest_result')==0 and observed.get('guest_pointer_bits')==32
    result=dict(proof,prepared_sha256_identity=sha(prepared_path),complete=True,passed=passed,
        returncode=returncode,guest_run=observed,stdout_sha256=sha(stdout))
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    count=proof.get('total_cases',proof['original_draw_count']+proof['synthetic_border_cases']+proof.get('synthetic_volume_cases',0))
    print(json.dumps(dict(passed=passed,original_draws=proof['original_draw_count'],
        new_border_cases=proof['synthetic_border_cases'],new_volume_cases=proof.get('synthetic_volume_cases',0),
        captured_depth_cpu_cases=proof.get('captured_depth_cpu_cases',0),
        dependent_ar_cases=proof.get('dependent_ar_cases',0),atomic_depth_rejection_cases=proof.get('atomic_depth_rejection_cases',0),
        compared_bytes=count*proof['compared_bytes_per_draw'],result=str(output/'result.json')),indent=2))
    if not passed:raise SystemExit('ILP32 state packing failed; result retained')

if __name__=='__main__':
    if '--ilp32' in sys.argv or '--consume-ilp32' in sys.argv:
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--ilp32',action='store_true')
        parser.add_argument('--consume-ilp32',type=Path)
        parser.add_argument('--consume-returncode',type=int)
        parser.add_argument('--output',type=Path,required=True)
        parser.add_argument('--plugin',type=Path,default=ROOT.parent/'pfista-halo-macos/build/macos/guest_rebase.dylib')
        parser.add_argument('--executor',type=Path,default=ROOT/'build/metal-poc/host-opaque-mad-corrected-validation/host_metal_probe')
        args=parser.parse_args()
        if args.consume_ilp32:
            if args.consume_returncode is None:parser.error('Observed process return code required')
            consume_ilp32(args.output.resolve(),args.consume_ilp32.resolve(),args.consume_returncode)
        else:build_ilp32(args.output,args.plugin.resolve(),args.executor.resolve())
    else:unittest.main()
