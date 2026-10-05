#!/usr/bin/env python3
"""Authored transparent BSP assets and independent shader/composition checks."""
import copy
import json
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import types
import unittest

from metal_poc_export import Cache, decode_bitmap_mipmaps
from metal_poc_transparent_bsp import append_transparent_bsp, bsp_transparent_material
from test_metal_teleporters import generic_reference

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT.parent/'pfista-halo-macos/assets/maps/bloodgulch.map'
HANGEMHIGH_MAP = ROOT.parent/'pfista-halo-macos/assets/maps/hangemhigh.map'
UPPER_COLORS = [[0., 0., 1., 1.], [1., 1., 1., 0.]]
# Independent tag-selector interpreter already tested for scenery. Rebind its
# source constants to the BSP's ONE-function upper colors, without duplicating
# the combiner decoder or mirroring the specialized Metal equations.
bsp_plasma_reference = types.FunctionType(generic_reference.__code__,
    dict(generic_reference.__globals__, CONSTANTS=UPPER_COLORS))


def original_fade(normal, coordinate, density, mode):
    visibility = 1.-min(1., max(0., coordinate))*density
    # BSP shader reads the decoded normal without model normalization.
    facing = abs(normal[0])
    factor = visibility if mode == 0 else (1.-facing)*visibility if mode == 1 else facing*visibility
    return min(1., max(0., factor))


def fixtures():
    rng = random.Random(196)
    for i in range(192):
        textures = [[rng.random() for _ in range(4)] for _ in range(4)]
        normal = [(-1., 0., .49, .5, 1., 1.001)[i%6], .2, .3]
        coordinate = (-.1, 0., .01, .5, 1., 1.1)[(i//6)%6]
        density = (0., .4, 1.)[(i//36)%3]
        kind, mode = (3, 0) if i%2 else (1, 2)
        color = textures[0] if kind == 3 else bsp_plasma_reference(textures)
        fade = original_fade(normal, coordinate, density, mode)
        expected = [min(1., max(0., x*fade)) for x in color[:3]]+[min(1., max(0., color[3]))]
        yield dict(textures=textures, normal=normal, coordinate=coordinate,
                   density=density, kind=kind, mode=mode, expected=expected)


HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cmath>
#include <cstdio>
#include <cstring>
struct Case { simd_float4 textures[4],normal,positionDensity; uint32_t kind,mode,pad[2]; };
struct Frame { simd_float4x4 vp; simd_float4 forwardExposure,plane,fog; };
struct Material { uint32_t kind,pad[3]; simd_float4 transform[4],u[4],v[4],r[4],center[4],colors[2]; };
static_assert(sizeof(Frame)==112 && sizeof(Material)==368 && sizeof(Case)==112,"ABI");
static simd_float4 array(NSArray *a) {return {[a[0] floatValue],[a[1] floatValue],[a[2] floatValue],a.count>3?[a[3] floatValue]:0};}
int main(int argc,char **argv) { @autoreleasepool {
 if(argc!=5)return2;
 id<MTLDevice>d=MTLCreateSystemDefaultDevice();if(!d)return3;
 NSError*e=nil;
 NSString*fogPath=[[@(argv[1]) stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"Fog.metal"];
 NSString*s=[NSString stringWithContentsOfFile:fogPath encoding:NSUTF8StringEncoding error:&e];
 s=[s stringByAppendingString:[NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:&e]];
 s=[s stringByAppendingString:[NSString stringWithContentsOfFile:@(argv[2]) encoding:NSUTF8StringEncoding error:&e]];
 s=[s stringByAppendingString:@"\nstruct BspCheckCase { float4 t[4],normal,positionDensity; uint kind,mode,pad[2]; };\nkernel void bsp_check(device const BspCheckCase *cases [[buffer(0)]],device float4 *out [[buffer(1)]],constant TeleporterFrameUniforms *frames [[buffer(2)]],uint i [[thread_position_in_grid]]) { BspCheckCase c=cases[i];float fade=transparent_bsp_vertex_fade(c.positionDensity.xyz,c.normal.xyz,frames[i],c.mode);float4 color=c.kind==3?c.t[0]:teleporter_plasma(c.t[0],c.t[1],c.t[2],c.t[3],float4(0,0,1,1),float4(1,1,1,0));out[i]=float4(clamp(color.rgb*fade,0.0,1.0),clamp(color.a,0.0,1.0));}\n"];
 id<MTLLibrary>l=[d newLibraryWithSource:s options:nil error:&e];if(!l){fprintf(stderr,"%s\n",e.description.UTF8String);return4;}
 id<MTLComputePipelineState>p=[d newComputePipelineStateWithFunction:[l newFunctionWithName:@"bsp_check"] error:&e];if(!p)return5;
 NSArray*records=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[3])] options:0 error:&e];NSUInteger n=records.count;
 id<MTLBuffer>input=[d newBufferWithLength:n*sizeof(Case) options:MTLResourceStorageModeShared],output=[d newBufferWithLength:n*16 options:MTLResourceStorageModeShared],frames=[d newBufferWithLength:n*sizeof(Frame) options:MTLResourceStorageModeShared];
 for(NSUInteger i=0;i<n;i++){NSDictionary*r=records[i];Case*c=((Case*)input.contents)+i;memset(c,0,sizeof(*c));for(int j=0;j<4;j++)c->textures[j]=array(r[@"textures"][j]);c->normal=array(r[@"normal"]);c->positionDensity={0,0,[r[@"coordinate"] floatValue],[r[@"density"] floatValue]};c->kind=[r[@"kind"] intValue];c->mode=[r[@"mode"] intValue];((Frame*)frames.contents)[i]={matrix_identity_float4x4,{1,0,0,1},{0,0,1,0},{c->positionDensity.w,0,0,0}};}
 id<MTLCommandQueue>q=[d newCommandQueue];id<MTLCommandBuffer>b=[q commandBuffer];id<MTLComputeCommandEncoder>ce=[b computeCommandEncoder];[ce setComputePipelineState:p];[ce setBuffer:input offset:0 atIndex:0];[ce setBuffer:output offset:0 atIndex:1];[ce setBuffer:frames offset:0 atIndex:2];[ce dispatchThreads:MTLSizeMake(n,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];[ce endEncoding];[b commit];[b waitUntilCompleted];if(b.error)return6;
 float maxError=0;
 for(NSUInteger i=0;i<n;i++){simd_float4 expected=array(records[i][@"expected"]),actual=((simd_float4*)output.contents)[i];for(int j=0;j<4;j++){float error=fabsf(expected[j]-actual[j]);maxError=fmaxf(error,maxError);if(!std::isfinite(actual[j])||error>2e-5){fprintf(stderr,"case%lu channel%d expected%.9g actual%.9g\n",i,j,expected[j],actual[j]);return7;}}}
 // Exercise the actual vertex+fragment entrypoints and additive RGB state.
 MTLRenderPipelineDescriptor*rp=[MTLRenderPipelineDescriptor new];rp.vertexFunction=[l newFunctionWithName:@"transparent_bsp_vertex"];rp.fragmentFunction=[l newFunctionWithName:@"transparent_bsp_fragment"];rp.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;rp.colorAttachments[0].blendingEnabled=YES;rp.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorOne;rp.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOne;rp.colorAttachments[0].writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;
 id<MTLRenderPipelineState>render=[d newRenderPipelineStateWithDescriptor:rp error:&e];if(!render){fprintf(stderr,"%s\n",e.description.UTF8String);return8;}
 MTLTextureDescriptor*td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;id<MTLTexture>target=[d newTextureWithDescriptor:td];
 float vertices[]={-1,-1,.5,0,0,.5,.5, 3,-1,.5,0,0,.5,.5, -1,3,.5,0,0,.5,.5};float normals[]={.6f,0,0,.6f,0,0,.6f,0,0};
 Frame frame={matrix_identity_float4x4,{1,0,0,1},{0,0,1,0},{.4f,0,0,0}};
 Material m={};for(int i=0;i<4;i++){m.transform[i]={1,1,0,0};m.u[i]={0,1,0,0};m.v[i]={0,1,0,0};m.r[i]={0,1,0,0};}m.colors[0]={0,0,1,1};m.colors[1]={1,1,1,0};
 simd_float4 fogUniforms[]={{0,0,1,0},{.7f,.8f,.9f,.4f}};simd_float4 lookupValue={.5f,.5f,.5f,.5f};id<MTLTexture>lookup=[d newTextureWithDescriptor:td];[lookup replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&lookupValue bytesPerRow:16];
 unsigned compositions=0;
 for(int test=0;test<24;test++){NSDictionary*r=records[test];m.kind=[r[@"kind"] intValue];m.pad[0]=[r[@"mode"] intValue];m.pad[1]=(test%3==1&&m.kind==3);id<MTLTexture>tex[4];for(int j=0;j<4;j++){tex[j]=[d newTextureWithDescriptor:td];simd_float4 t=array(r[@"textures"][j]);[tex[j] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:&t bytesPerRow:16];}
 MTLRenderPassDescriptor*pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;pass.colorAttachments[0].clearColor=MTLClearColorMake(.125,.25,.375,.625);
 b=[q commandBuffer];id<MTLRenderCommandEncoder>re=[b renderCommandEncoderWithDescriptor:pass];[re setRenderPipelineState:render];[re setVertexBytes:vertices length:sizeof(vertices) atIndex:0];[re setVertexBytes:&frame length:sizeof(frame) atIndex:1];[re setVertexBytes:normals length:sizeof(normals) atIndex:2];[re setVertexBytes:&m length:sizeof(m) atIndex:3];[re setFragmentBytes:&frame length:sizeof(frame) atIndex:0];[re setFragmentBytes:&m length:sizeof(m) atIndex:1];[re setFragmentBytes:fogUniforms length:sizeof(fogUniforms) atIndex:2];[re setFragmentTexture:lookup atIndex:4];for(int j=0;j<4;j++)[re setFragmentTexture:tex[j] atIndex:j];[re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[re endEncoding];[b commit];[b waitUntilCompleted];if(b.error)return9;
 simd_float4 actual;[target getBytes:&actual bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];NSArray*er=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[4])] options:0 error:&e];simd_float4 expected=array(er[test]);for(int j=0;j<4;j++){float error=fabsf(expected[j]-actual[j]);maxError=fmaxf(error,maxError);if(!std::isfinite(actual[j])||error>2e-5){fprintf(stderr,"composition%d channel%d expected%.9g actual%.9g\n",test,j,expected[j],actual[j]);return10;}}compositions++;}
 printf("%lu BSP generic/fade cases, %u actual additive compositions passed; max error %.9g\n",n,compositions,maxError);return0;
}}
'''.replace('return', 'return ')


class TransparentBspTests(unittest.TestCase):
    def test_authored_sections_permutations_and_mips(self):
        if not MAP.exists():
            self.skipTest('User-owned Blood Gulch cache unavailable')
        cache = Cache(MAP)
        _, scenario, _ = cache.tag(cache.u32(cache.tag_offset+4))
        _, pointer = cache.unpack('<II', scenario+0x5a4)
        offset, size, address = cache.unpack('<III', cache.pointer(pointer))
        def bsp_ptr(pointer, length=1):
            relative = pointer-address
            self.assertGreaterEqual(relative, 0)
            self.assertLessEqual(relative+length, size)
            return offset+relative
        bsp = bsp_ptr(cache.u32(offset))
        refs = []
        def texture(tid, permutation, is_permutation):
            self.assertTrue(is_permutation)
            cls, bitmap, name = cache.tag(tid)
            self.assertEqual(cls, 'bitm')
            count, ptr = cache.unpack('<II', bitmap+96)
            selected = permutation%count
            image = cache.pointer(ptr, count*48)+selected*48
            w,h,depth,kind,fmt,flags = cache.unpack('<6H', image+4)
            self.assertEqual((depth,kind), (1,0))
            levels=decode_bitmap_mipmaps(cache.span(cache.u32(image+24),cache.u32(image+28)),
                w,h,fmt,flags,cache.unpack('<h',image+20)[0])
            self.assertGreater(len(levels),1,name)
            refs.append((name,selected,len(levels)))
            return len(refs)+1
        vertices=bytearray(struct.pack('<7f',*([0.]*7)))
        indices=bytearray()
        result=append_transparent_bsp(cache,bsp,bsp_ptr,texture,vertices,indices)
        self.assertEqual(len(result['meshes']),44)
        self.assertEqual(len(indices)//12,132)
        self.assertEqual((result['first_vertex'],len(vertices)//28),(1,257))
        self.assertEqual(len(result['normal_data']),256*12)
        self.assertEqual([m['kind'] for m in result['meshes']].count(1),2)
        self.assertEqual([m['kind'] for m in result['meshes']].count(3),42)
        self.assertEqual([m['is_decal'] for m in result['meshes']].count(True),2)
        self.assertEqual(result['meshes'][1]['constant_colors'],UPPER_COLORS)
        red=result['meshes'][4]
        self.assertEqual((red['source_surface_first'],red['source_surface_count']),(5423,2))
        self.assertEqual(red['fade_mode'],0)
        self.assertFalse(red['is_decal'])
        self.assertTrue(any('mp lights small strips red' in r[0] for r in refs))
        self.assertTrue(any('black light' in r[0] for r in refs))

    def test_vertex_fade_uses_raw_normal_and_density(self):
        self.assertAlmostEqual(original_fade([.6,.8,0],.5,.4,2),.48)
        self.assertAlmostEqual(original_fade([.6,.8,0],.5,.4,0),.8)
        # A near-unit compressed normal must not be silently normalized.
        self.assertAlmostEqual(original_fade([.6,.8,.5],.5,.4,2),.48)

    def test_hangemhigh_authored_lights_counter_geometry_and_mips(self):
        if not HANGEMHIGH_MAP.exists():
            self.skipTest('User-owned Hang Em High cache unavailable')
        cache = Cache(HANGEMHIGH_MAP)
        shader_id = 0xe801068b
        cls, shader, name = cache.tag(shader_id)
        self.assertEqual((cls, name), ('sotr', r'levels\test\hangemhigh\shaders\hangemhigh blue light'))
        self.assertEqual(cache.unpack('<BB', shader+0x28), (0, 0))
        # A nonzero numeric counter remains inactive without flag8. Probe5
        # explicitly; it must neither select another atlas frame nor alter
        # shader arithmetic (the current authored cache stores counter0).
        refs = []
        def texture(tid, permutation, is_permutation):
            self.assertTrue(is_permutation)
            self.assertEqual((tid, permutation), (0xe802068c, 0))
            cls, bitmap, name = cache.tag(tid)
            self.assertEqual((cls, name), ('bitm', r'levels\b30\bitmaps\lights small strips'))
            count, pointer = cache.unpack('<II', bitmap+96)
            self.assertEqual(count, 1)
            image = cache.pointer(pointer, count*48)
            w,h,depth,kind,fmt,flags = cache.unpack('<6H', image+4)
            self.assertEqual((w,h,depth,kind,fmt,flags), (1024,256,1,0,14,131))
            levels = decode_bitmap_mipmaps(cache.span(cache.u32(image+24),cache.u32(image+28)),
                w,h,fmt,flags,cache.unpack('<h',image+20)[0])
            self.assertEqual([(m['width'],m['height']) for m in levels],
                [(1024,256),(512,128),(256,64),(128,32),(64,16),(32,8),(16,4),(8,2),(4,1)])
            refs.append(tid)
            return 1
        supported = bsp_transparent_material(cache, shader_id, 0, texture)
        self.assertEqual((supported['kind'],supported['blend'],supported['fade_mode']), (3,'add',0))
        self.assertFalse(supported['is_decal'])
        edited = copy.copy(cache)
        raw = bytearray(cache.data)
        raw[shader+0x28] = 5
        edited.data = bytes(raw)
        self.assertEqual(bsp_transparent_material(edited, shader_id, 0, texture), supported)
        raw[shader+0x29] = 8
        edited.data = bytes(raw)
        def forbidden_texture(*_):
            self.fail('Numeric shader attempted texture export')
        with self.assertRaisesRegex(ValueError, 'numeric'):
            bsp_transparent_material(edited, shader_id, 0, forbidden_texture)
        _, scenario, _ = cache.tag(cache.u32(cache.tag_offset+4))
        _, pointer = cache.unpack('<II', scenario+0x5a4)
        offset, size, address = cache.unpack('<III', cache.pointer(pointer))
        def bsp_ptr(pointer, length=1):
            relative = pointer-address
            self.assertGreaterEqual(relative, 0)
            self.assertLessEqual(relative+length, size)
            return offset+relative
        bsp = bsp_ptr(cache.u32(offset))
        vertices = bytearray(struct.pack('<7f', *([0.]*7)))
        indices = bytearray()
        result = append_transparent_bsp(cache,bsp,bsp_ptr,texture,vertices,indices)
        self.assertEqual((len(result['meshes']),len(indices)//12,len(vertices)//28), (176,358,727))
        self.assertEqual((result['first_vertex'],len(result['normal_data'])), (1,726*12))
        self.assertEqual((result['meshes'][0]['source_surface_first'],
                          result['meshes'][-1]['source_surface_first']), (2860,3216))
        self.assertTrue(all(m['name']==supported['name'] and m['kind']==3 and
                            m['textures']==[1,0,0,0] and not m['is_decal'] for m in result['meshes']))
        # Compare the first emitted triangle to its exact cache surface indices
        # independently of the helper's loop and shared-buffer seed offset.
        _, surfaces_pointer = cache.unpack('<II', bsp+0xf8)
        authored_first = cache.unpack('<3H', bsp_ptr(surfaces_pointer)+2860*6)
        self.assertEqual(struct.unpack('<3I',indices[:12]), tuple(index+1 for index in authored_first))

    def test_unsupported_material_state_rejects_before_texture_export(self):
        if not MAP.exists():
            self.skipTest('User-owned Blood Gulch cache unavailable')
        cache = Cache(MAP)
        for index in range(cache.tag_count):
            record = cache.tag_offset+36+index*32
            if cache.span(record, 4) != b'rtos':
                continue
            tag_id = cache.u32(record+12)
            _, shader, name = cache.tag(tag_id)
            if name == r'levels\test\bloodgulch\shaders\bloodgulch light red':
                break
        else:
            self.fail('Authored red light tag unavailable')
        _, pointer = cache.unpack('<II', shader+0x54)
        bitmap_map = cache.pointer(pointer, 100)
        mutations = [
            ('alpha test', '<B', shader+0x29, 4),
            ('numeric counter', '<B', shader+0x29, 8),
            ('lit vertex program', '<H', shader, 4),
            ('alpha blend', '<h', shader+0x2c, 0),
            ('explicit combiner', '<I', shader+0x60, 1),
            ('sampler clamp', '<H', bitmap_map, 1),
            ('mip bias', '<f', bitmap_map+24, .25),
        ]
        for label, fmt, offset, value in mutations:
            with self.subTest(label=label):
                edited = copy.copy(cache)
                raw = bytearray(cache.data)
                struct.pack_into(fmt, raw, offset, value)
                edited.data = bytes(raw)
                def forbidden_texture(*_):
                    self.fail('Unsupported material attempted texture export')
                with self.assertRaises(ValueError):
                    bsp_transparent_material(edited, tag_id, 0, forbidden_texture)

    def test_native_shader_and_composition(self):
        data=list(fixtures())
        compositions=[]
        for index,record in enumerate(data[:24]):
            color=record['textures'][0] if record['kind']==3 else bsp_plasma_reference(record['textures'])
            fade=original_fade([.6,0,0],.5,.4,record['mode'])
            second_fog=.8 if index%3==1 and record['kind']==3 else 1.
            compositions.append([background+min(1.,max(0.,value*fade))*second_fog
                                 for value,background in zip(color[:3],(.125,.25,.375))]+[.625])
        with tempfile.TemporaryDirectory(prefix='halo-transparent-bsp-') as folder:
            folder=Path(folder)
            (folder/'test.mm').write_text(HARNESS)
            (folder/'fixtures.json').write_text(json.dumps(data))
            (folder/'compositions.json').write_text(json.dumps(compositions))
            subprocess.run(['xcrun','clang++','-std=c++17','-O2','-fobjc-arc',folder/'test.mm',
                            '-framework','Foundation','-framework','Metal','-o',folder/'test'],check=True)
            result=subprocess.run([folder/'test',ROOT/'port/macos/metal-poc/Teleporter.metal',
                ROOT/'port/macos/metal-poc/TransparentBsp.metal',folder/'fixtures.json',
                folder/'compositions.json'],text=True,capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('192 BSP generic/fade cases, 24 actual additive compositions passed',result.stdout)
            print(result.stdout.strip())


if __name__=='__main__':
    unittest.main()
