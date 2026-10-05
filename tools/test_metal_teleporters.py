#!/usr/bin/env python3
"""Original teleporter assets and independent generic-combiner/Metal checks."""
import json
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from metal_poc_export import Cache, decode_bitmap_mipmaps
from metal_poc_teleporters import (append_teleporters, PLASMA_STAGES, PLASMA_SHADER,
                                  rotation_basis, transform_vector, original_bump_palette,
                                  decode_p8_bump_mipmaps)

ROOT = Path(__file__).resolve().parents[1]
RETAIL_MAP = ROOT.parent / 'pfista-halo-macos/assets/maps/bloodgulch.map'
CONSTANTS = [[0.,0.,89/255,102/255], [0.,84/255,108/255,0.]]


def mapped(value, mapping):
    unsigned = max(value,0.)
    return (unsigned,1-unsigned,2*unsigned-1,1-2*unsigned,
            value-.5,.5-value,value,-value)[mapping]


def generic_reference(textures):
    """General stage interpreter from the tag selector tables, not MSL math."""
    regs = {'r0': [0.,0.,0.,textures[0][3]], 'r1': [0.,0.,0.,0.],
            'v0': [0.,0.,0.,1.], 'v1': [0.,0.,0.,1.]}
    registers = [None]*5+['t0','t1','t2','t3','v0','v1','r0','r1','c0','c1']
    for i,t in enumerate(textures):
        regs[f't{i}'] = list(t)
    for stage_index, selectors in enumerate(PLASMA_STAGES):
        regs['c0'] = CONSTANTS[0] if stage_index == 0 else CONSTANTS[1] if stage_index == 6 else [0.]*4
        regs['c1'] = [0.]*4
        old_alpha = regs['r0'][3]
        def read(index, mapping, alpha):
            if index < 5:
                value = (0.,1.,.5,-1.,-0.5)[index]
                result = mapped(value,mapping)
                return result if alpha else [result]*3
            channel = 3 if alpha else None
            if index >= 15:
                index -= 10
                channel = 2 if alpha else 3
            value = regs[registers[index]]
            if channel is not None:
                result = mapped(value[channel],mapping)
                return result if alpha else [result]*3
            return [mapped(x,mapping) for x in value[:3]]
        rgb = [read(selectors[i],selectors[i+1],False) for i in range(0,8,2)]
        a = [read(selectors[i],selectors[i+1],True) for i in range(14,22,2)]
        color_outputs = [[rgb[0][c]*rgb[1][c] for c in range(3)],
                         [rgb[2][c]*rgb[3][c] for c in range(3)]]
        alpha_outputs = [a[0]*a[1],a[2]*a[3]]
        color_outputs.append([x+y for x,y in zip(*color_outputs)])
        alpha_outputs.append(alpha_outputs[int(old_alpha>=.5)] if stage_index in (3,4)
                             else sum(alpha_outputs))
        def output_mapping(x,index):
            return max(-1.,min(1.,(x,(x-.5)*2,x*2,x*4,x-.5,x*.5)[index]))
        destinations = [None,'r0','r1','v0','v1','t0','t1','t2','t3']
        # Stage outputs are simultaneous: all reads above occur before writes.
        for output,destination in zip(color_outputs,(selectors[8],selectors[10],selectors[12])):
            if destination:
                regs[destinations[destination]][:3] = [output_mapping(x,selectors[13]) for x in output]
        for output,destination in zip(alpha_outputs,selectors[22:25]):
            if destination:
                regs[destinations[destination]][3] = output_mapping(output,selectors[25])
    return [max(x,0.) for x in regs['r0']]


def f32(value):
    return struct.unpack('<f',struct.pack('<f',value))[0]


def original_slide(time):
    # Independent original CPU byte-table construction and lookup. The table
    # is built once, rather than evaluating the shader helper's equation.
    table = [int(f32(math.fmod(f32(i*f32(.027343748)),1)*255)) for i in range(1024)]
    scaled = f32(f32(time)*f32(25.6))
    fraction = f32(math.fmod(scaled,1))
    index = int(f32(scaled-fraction))&1023
    first, second = f32(table[index]/255), f32(table[(index+1)&1023]/255)
    if first>.75 and second<.25:
        second = f32(second+1)
    value = f32(f32(f32(1-fraction)*first)+f32(second*fraction))
    return f32(value-1) if value>1 else value


def authored_maps(kind):
    # Actual tag animation records, checked separately by the asset test.
    scrolls = ((10,-1,6,1),(11,1,7,-1),(1,1,1,1),(1,1,1,1)) if kind == 1 else (
        (6,1,-20,1),(-4,1,15,1),(1,1,1,1),(1,0,1,0))
    return [dict(scale_offset=[1.,1.05 if kind==2 and i==2 else 1.,0.,0.],
                 u_animation=[6 if i<2 else 0,up,0.,us],
                 v_animation=[6 if i<2 else 0,vp,0.,vs],
                 r_animation=[0,1.,0.,1. if kind==1 and i<2 else 360.],
                 rotation_center=[0.,0.,0.,0.])
            for i,(up,us,vp,vs) in enumerate(scrolls)]


def original_uv(record,time):
    def animation(parameters):
        function,period,phase,scale = parameters
        value = 1. if function == 0 else original_slide(f32(f32(phase+f32(time))/(period or 1)))
        return f32(value*scale)
    sx,sy,ox,oy = record['scale_offset']
    rotation,cx,cy,_ = record['rotation_center']
    angle = math.radians(rotation+animation(record['r_animation']))
    c,s = math.cos(angle),math.sin(angle)
    # Reference affine rows from shaders.c: UV dot row + row.w.
    u = ox-cx+animation(record['u_animation'])
    v = oy-cy+animation(record['v_animation'])
    return [c*sx*.23-s*sy*(-.41)+c*u-s*v+cx,
            s*sx*.23+c*sy*(-.41)+c*v+s*u+cy]


def fixtures():
    rng = random.Random(191)
    for i in range(240):
        textures = [[rng.random() for _ in range(4)] for _ in range(4)]
        if i<16:
            for j,t in enumerate(textures):
                t[3] = (0.,.49,.5,1.)[(i+j)%4]
        kind = 1 if i%2 == 0 else 2
        expected = generic_reference(textures) if kind == 1 else [math.prod(t[c] for t in textures[:3]) for c in range(4)]
        time = (i-120)*.373
        maps = authored_maps(kind)
        yield dict(name=f'combiner-{i}',kind=kind,textures=textures,constants=CONSTANTS,
                   time=time,slide=original_slide(time),expected=expected,maps=maps,
                   uv=[original_uv(m,time) for m in maps])


NATIVE = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cmath>
#include <cstdio>
struct Vertex { float x,y,z,u,v,lu,lv; };
struct Normal { float x,y,z; };
struct Frame { simd_float4x4 vp;simd_float4 forwardExposure,plane,parameters; };
struct Material { uint32_t kind,pad[3];simd_float4 scaleOffset[4],u[4],v[4],r[4],rotation[4],color[2]; };
static_assert(sizeof(Vertex)==28,"Vertex ABI");
static_assert(sizeof(Normal)==12,"Normal ABI");
static_assert(sizeof(Frame)==112,"Frame ABI");
static_assert(sizeof(Material)==368,"Material ABI");
static bool near(float a,float b,float tolerance=.000005f){return std::isfinite(a)&&fabsf(a-b)<=tolerance;}
int main(int argc,char **argv){@autoreleasepool{
    if(argc!=3)return 2;
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device)return 77;
    NSError *error=nil;
    NSString *source=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]] encoding:NSUTF8StringEncoding error:&error];
    source=[source stringByAppendingString:@"\nkernel void validate_teleporter(constant float4 *v [[buffer(0)]],constant uint &kind [[buffer(1)]],constant float &time [[buffer(2)]],device float4 *out [[buffer(3)]],constant TeleporterMaterialUniforms &material [[buffer(4)]]) {out[0]=kind==1?teleporter_plasma(v[0],v[1],v[2],v[3],v[4],v[5]):teleporter_cone(v[0],v[1],v[2]);out[1]=float4(teleporter_periodic_slide(time),0,0,0);for(uint j=0;j<4;j++)out[2+j]=float4(teleporter_uv(float2(.23,-.41),j,time,material),0,0);}\n"];
    MTLCompileOptions *options=[MTLCompileOptions new];options.fastMathEnabled=NO;
    id<MTLLibrary> library=[device newLibraryWithSource:source options:options error:&error];
    if(!library){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 3;}
    id<MTLComputePipelineState> compute=[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"validate_teleporter"] error:&error];
    if(!compute)return 4;
    id<MTLCommandQueue> queue=[device newCommandQueue];
    NSArray *cases=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]] options:0 error:&error];
    unsigned passed=0;float maxError=0;
    for(NSDictionary *fixture in cases){
        simd_float4 values[6];
        for(unsigned i=0;i<4;i++)for(unsigned c=0;c<4;c++)values[i][c]=[fixture[@"textures"][i][c] floatValue];
        for(unsigned i=0;i<2;i++)for(unsigned c=0;c<4;c++)values[4+i][c]=[fixture[@"constants"][i][c] floatValue];
        uint32_t kind=[fixture[@"kind"] unsignedIntValue];float time=[fixture[@"time"] floatValue];
        Material material={};material.kind=kind;
        for(unsigned j=0;j<4;j++)for(unsigned c=0;c<4;c++){
            NSDictionary *map=fixture[@"maps"][j];
            material.scaleOffset[j][c]=[map[@"scale_offset"][c] floatValue];
            material.u[j][c]=[map[@"u_animation"][c] floatValue];
            material.v[j][c]=[map[@"v_animation"][c] floatValue];
            material.r[j][c]=[map[@"r_animation"][c] floatValue];
            material.rotation[j][c]=[map[@"rotation_center"][c] floatValue];
        }
        id<MTLBuffer> output=[device newBufferWithLength:96 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:compute];[encoder setBytes:values length:sizeof(values) atIndex:0];
        [encoder setBytes:&kind length:4 atIndex:1];[encoder setBytes:&time length:4 atIndex:2];[encoder setBuffer:output offset:0 atIndex:3];
        [encoder setBytes:&material length:sizeof(material) atIndex:4];
        [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 5;
        float *actual=(float*)output.contents;
        for(unsigned c=0;c<4;c++){
            float expected=[fixture[@"expected"][c] floatValue];maxError=fmaxf(maxError,fabsf(actual[c]-expected));
            if(!near(actual[c],expected)){fprintf(stderr,"%s ch%u %.9g expected%.9g\n",[fixture[@"name"] UTF8String],c,actual[c],expected);return 6;}
        }
        if(!near(actual[4],[fixture[@"slide"] floatValue])){fprintf(stderr,"slide time%.9g actual%.9g expected%.9g\n",time,actual[4],[fixture[@"slide"] floatValue]);return 7;}
        for(unsigned j=0;j<4;j++)for(unsigned c=0;c<2;c++)if(!near(actual[8+j*4+c],[fixture[@"uv"][j][c] floatValue],.000015f)){
            fprintf(stderr,"UV kind%u time%.9g map%u ch%u actual%.9g expected%.9g\n",kind,time,j,c,actual[8+j*4+c],[fixture[@"uv"][j][c] floatValue]);return 12;
        }
        passed++;
    }
    // Actual vertex/fragment bindings, angle/distance fade, and RGB-only ONE+
    // ONE composition. Atmospheric fade clamps coordinate before raw density.
    MTLRenderPipelineDescriptor *desc=[MTLRenderPipelineDescriptor new];
    desc.vertexFunction=[library newFunctionWithName:@"teleporter_vertex"];
    desc.fragmentFunction=[library newFunctionWithName:@"teleporter_fragment"];
    desc.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
    desc.colorAttachments[0].blendingEnabled=YES;
    desc.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorOne;
    desc.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOne;
    desc.colorAttachments[0].writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;
    id<MTLRenderPipelineState> render=[device newRenderPipelineStateWithDescriptor:desc error:&error];
    if(!render){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 8;}
    const Vertex vertices[4]={{-1,-1,0,0,0,0,0},{1,-1,0,1,0,0,0},{-1,1,0,0,1,0,0},{1,1,0,1,1,0,0}};
    unsigned compositions=0;
    for(unsigned kind=1;kind<=2;kind++)for(float angle:{0.f,.25f,.5f,1.f})for(float coordinate:{-1.f,.5f,2.f}){
        NSDictionary *fixture=cases[(kind-1)*2];
        simd_float4 values[4];id<MTLTexture> textures[4];
        for(unsigned i=0;i<4;i++){
            for(unsigned c=0;c<4;c++)values[i][c]=[fixture[@"textures"][i][c] floatValue];
            MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;
            textures[i]=[device newTextureWithDescriptor:td];
            [textures[i] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&values[i] bytesPerRow:16];
        }
        // Select a separately provided expectation for each material kind.
        NSArray *reference=kind==1?cases[0][@"expected"]:cases[1][@"expected"];
        if(kind==2){fixture=cases[1];for(unsigned i=0;i<4;i++){
            for(unsigned c=0;c<4;c++)values[i][c]=[fixture[@"textures"][i][c] floatValue];
            [textures[i] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&values[i] bytesPerRow:16];}}
        Material material={};material.kind=kind;
        for(unsigned i=0;i<4;i++){material.scaleOffset[i]={1,1,0,0};material.u[i]={0,1,0,0};material.v[i]={0,1,0,0};material.r[i]={0,1,0,0};}
        for(unsigned i=0;i<2;i++)for(unsigned c=0;c<4;c++)material.color[i][c]=[fixture[@"constants"][i][c] floatValue];
        Frame frame={matrix_identity_float4x4,{0,0,1,1},{0,0,0,coordinate},{.4f,0,0,0}};
        Normal normals[4];for(auto &n:normals)n={sqrtf(1-angle*angle),0,-angle};
        MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget;
        id<MTLTexture> target=[device newTextureWithDescriptor:td];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(.15,.25,.35,.83);
        id<MTLCommandBuffer> command=[queue commandBuffer];id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        [encoder setRenderPipelineState:render];[encoder setVertexBytes:vertices length:sizeof(vertices) atIndex:0];
        [encoder setVertexBytes:&frame length:sizeof(frame) atIndex:1];[encoder setVertexBytes:normals length:sizeof(normals) atIndex:2];
        [encoder setVertexBytes:&material length:sizeof(material) atIndex:3];
        [encoder setFragmentBytes:&frame length:sizeof(frame) atIndex:0];[encoder setFragmentBytes:&material length:sizeof(material) atIndex:1];
        for(unsigned i=0;i<4;i++)[encoder setFragmentTexture:textures[i] atIndex:i];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];[encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 9;
        float actual[4];[target getBytes:actual bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        float fade=angle*(1-fminf(1,fmaxf(0,coordinate))*.4f),background[3]={.15,.25,.35};
        for(unsigned c=0;c<3;c++){
            float expected=[reference[c] floatValue]*fade+background[c];
            if(!near(actual[c],expected)){fprintf(stderr,"render kind%u angle%.2f coord%.2f ch%u actual%.9g expected%.9g\n",kind,angle,coordinate,c,actual[c],expected);return 10;}
        }
        if(!near(actual[3],.83f))return 11;
        compositions++;
    }
    printf("%u generic/cone and original-slide cases, %u additive/fade compositions passed; max error %.9g\n",passed,compositions,maxError);
    return 0;
}}
'''


class TeleporterTests(unittest.TestCase):
    def test_original_p8_bump_palette_alpha_and_mip_expansion(self):
        palette = original_bump_palette()
        self.assertEqual(len(palette),256)
        self.assertEqual(sum(bool(x>>24) for x in palette),249)
        self.assertEqual(palette[0],0xff7a19cc)
        transparent = next(i for i,color in enumerate(palette) if color>>24 == 0)
        # Swizzled4x4 level0 +2x2 +1x1 authored levels, each constant index.
        levels = decode_p8_bump_mipmaps(bytes([0])*16+bytes([transparent])*4+bytes([1]),
                                       4,4,137,2)
        self.assertEqual([(l['width'],l['height']) for l in levels],[(4,4),(2,2),(1,1)])
        self.assertEqual(levels[0]['rgba'],bytes([122,25,204,255])*16)
        self.assertEqual(levels[1]['rgba'][3::4],bytes(4))
        self.assertEqual(levels[2]['rgba'],bytes([126,25,204,255]))

    def test_original_euler_axes_and_scale(self):
        basis = rotation_basis((math.pi/2,0,0))
        expected = ((0,1,0),(-1,0,0),(0,0,1))
        for a,b in zip(basis,expected):
            for x,y in zip(a,b):
                self.assertAlmostEqual(x,y)
        self.assertEqual(transform_vector((1,2,3),rotation_basis((0,0,0))), (1,2,3))

    @unittest.skipUnless(RETAIL_MAP.is_file(), 'User-owned Xbox cache is unavailable')
    def test_original_placements_materials_geometry_and_authored_mips(self):
        cache = Cache(RETAIL_MAP)
        _,scenario,_ = cache.tag(cache.u32(cache.tag_offset+4))
        texture_refs = []
        def texture(tag,index,permutation):
            self.assertEqual(index,0)
            self.assertTrue(permutation)
            cls,bitmap,name = cache.tag(tag)
            self.assertEqual(cls,'bitm')
            n,p = cache.unpack('<II',bitmap+0x60)
            self.assertGreater(n,0)
            image = cache.pointer(p,n*48)
            w,h,depth,kind,fmt,flags = cache.unpack('<6H',image+4)
            self.assertEqual((depth,kind),(1,0))
            mip_count = cache.unpack('<H',image+20)[0]
            raw = cache.span(cache.u32(image+24),cache.u32(image+28))
            levels = (decode_p8_bump_mipmaps(raw,w,h,flags,mip_count) if fmt == 17 else
                      decode_bitmap_mipmaps(raw,w,h,fmt,flags,mip_count))
            self.assertGreater(len(levels),1,name)
            texture_refs.append(name)
            return len(texture_refs)+1
        vertices,indices = bytearray(struct.pack('<7f',*([0.]*7))),bytearray()
        result = append_teleporters(cache,scenario,vertices,indices,texture)
        self.assertEqual(result['placements'],[27,28])
        self.assertEqual(len(result['meshes']),10)
        self.assertEqual(len(vertices)//28,693)
        self.assertEqual(len(indices)//12,368)
        self.assertEqual(len(result['normal_data']),len(vertices)//28*12)
        self.assertEqual(result['normal_data'][:12],bytes(12))
        self.assertEqual([m['kind'] for m in result['meshes']], [1,0,0,0,2]*2)
        self.assertEqual(result['meshes'][0]['constant_colors'],CONSTANTS)
        self.assertTrue(result['meshes'][1]['model_environment'])
        self.assertNotEqual(result['meshes'][1]['alpha_test_texture'],0)
        self.assertEqual(result['meshes'][1]['detail_textures'],[1,0,0])
        self.assertEqual(result['meshes'][1]['micro_function'],1)
        for mesh in (result['meshes'][0],result['meshes'][4]):
            for actual,reference in zip(mesh['maps'],authored_maps(mesh['kind'])):
                for key in actual:
                    for x,y in zip(actual[key],reference[key]):
                        self.assertAlmostEqual(x,y,places=6)
        self.assertIn(r'scenery\teleporter_base\bitmaps\teleporter_dust',texture_refs)
        self.assertIn(r'levels\a50\devices\prison door\bitmaps\energy plasma',texture_refs)
        self.assertTrue(all(m['model_scale']==1 for m in result['meshes']))
        self.assertEqual([m['index_count'] for m in result['meshes'][:5]], [12,198,252,54,36])

    @unittest.skipUnless(RETAIL_MAP.is_file(), 'User-owned Xbox cache is unavailable')
    def test_only_current_bsp_scenery_is_placed(self):
        cache = Cache(RETAIL_MAP)
        cache.data = bytearray(cache.data)
        _,scenario,_ = cache.tag(cache.u32(cache.tag_offset+4))
        count,pointer = cache.unpack('<II',scenario+0x210)
        placements = cache.pointer(pointer,count*72)
        # Exercise actual scenery placement records. No-membership and a
        # different BSP's bit must both exclude placement24; BSP0 includes it.
        for membership,expected in ((0,[27,28]),(2,[27,28]),(1,[24,27,28])):
            with self.subTest(membership=membership):
                struct.pack_into('<H',cache.data,placements+24*72+32,membership)
                result = append_teleporters(cache,scenario,bytearray(),bytearray(),lambda *args: 0)
                self.assertEqual(result['placements'],expected)
                self.assertEqual(len(result['meshes']),len(expected)*5)
                for placement_index in (27,28):
                    source = placements+placement_index*72
                    mesh = next(m for m in result['meshes'] if m['placement_index']==placement_index)
                    self.assertEqual(mesh['position'],cache.unpack('<3f',source+8))
                    self.assertEqual(mesh['rotation'],cache.unpack('<3f',source+20))

    @unittest.skipUnless(RETAIL_MAP.is_file(), 'User-owned Xbox cache is unavailable')
    def test_authored_membership_matches_original_collision_leaf_test(self):
        cache = Cache(RETAIL_MAP)
        _,scenario,_ = cache.tag(cache.u32(cache.tag_offset+4))
        count,pointer = cache.unpack('<II',scenario+0x5a4)
        self.assertEqual(count,1)
        offset,size,address = cache.unpack('<III',cache.pointer(pointer,32))
        def bsp_pointer(pointer):
            self.assertGreaterEqual(pointer,address)
            self.assertLess(pointer,address+size)
            return offset+pointer-address
        bsp = bsp_pointer(cache.u32(offset))
        count,pointer = cache.unpack('<II',bsp+0xb0)
        self.assertEqual(count,1)
        collision = bsp_pointer(pointer)
        nodes = bsp_pointer(cache.u32(collision+4))
        planes = bsp_pointer(cache.u32(collision+16))
        placements = cache.pointer(cache.u32(scenario+0x214))
        palette = cache.pointer(cache.u32(scenario+0x220))
        for index,expected in ((24,-1),(27,1133),(28,1431)):
            placement = placements+index*72
            point = cache.unpack('<3f',placement+8)
            _,obj,_ = cache.tag(cache.u32(palette+cache.unpack('<h',placement)[0]*48+12))
            self.assertEqual(cache.unpack('<3f',obj+20),(0.,0.,0.))
            node = 0
            for _ in range(65536):
                plane,back,front = cache.unpack('<iii',nodes+node*12)
                self.assertGreaterEqual(plane,0)
                normal = cache.unpack('<4f',planes+plane*16)
                distance = f32(f32(f32(f32(normal[0]*point[0])+f32(normal[1]*point[1]))+
                                   f32(normal[2]*point[2]))-normal[3])
                node = front if distance >= 0 else back
                if node < 0:
                    break
            else:
                self.fail('Collision BSP traversal did not reach a leaf')
            leaf = -1 if node == -1 else node & 0x7fffffff
            self.assertEqual(leaf,expected)
            self.assertEqual(cache.unpack('<H',placement+32)[0],int(leaf!=-1))

    @unittest.skipUnless(RETAIL_MAP.is_file(), 'User-owned Xbox cache is unavailable')
    def test_unsupported_generic_stage_rejected(self):
        cache = Cache(RETAIL_MAP)
        cache.data = bytearray(cache.data)
        _,scenario,_ = cache.tag(cache.u32(cache.tag_offset+4))
        for i in range(cache.tag_count):
            cls,shader,name = cache.tag(cache.u32(cache.tag_offset+36+i*32+12))
            if name == PLASMA_SHADER:
                self.assertEqual(cls,'sotr')
                stage = cache.pointer(cache.unpack('<II',shader+0x60)[1])
                struct.pack_into('<h',cache.data,stage+62,2) # change input mapping1 to2
                break
        with self.assertRaisesRegex(ValueError,'Unsupported teleporter generic combiner'):
            append_teleporters(cache,scenario,bytearray(),bytearray(),lambda *args: 0)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang++'), 'Metal runtime required')
    def test_gpu_combiners_original_slide_and_additive_angle_fog(self):
        with tempfile.TemporaryDirectory(prefix='halo-metal-teleporter-') as directory:
            folder = Path(directory)
            (folder/'cases.json').write_text(json.dumps(list(fixtures())))
            (folder/'validate.mm').write_text(NATIVE)
            executable = folder/'validate'
            result = subprocess.run(['clang++','-std=c++17','-O2','-fobjc-arc','-Wall','-Wextra',
                                     str(folder/'validate.mm'),'-framework','Foundation','-framework','Metal',
                                     '-o',str(executable)], capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result = subprocess.run([str(executable),str(ROOT/'port/macos/metal-poc/Teleporter.metal'),
                                     str(folder/'cases.json')],capture_output=True,text=True)
            if result.returncode == 77:
                self.skipTest('GPU is unavailable in this sandbox')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('240 generic/cone and original-slide cases, 24 additive/fade compositions passed',result.stdout)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
