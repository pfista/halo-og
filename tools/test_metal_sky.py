#!/usr/bin/env python3
"""Verify original sky assets, camera transform, combiners and alpha composition."""
import contextlib
import io
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from metal_poc_export import Cache, export


ROOT = Path(__file__).resolve().parents[1]
RETAIL_MAP = ROOT.parent / 'pfista-halo-macos/assets/maps/bloodgulch.map'


def sky_cases():
    # Independent equations decoded from the original Chicago combiner table:
    # copy t0; multiply the next map; add the third map while retaining t0 alpha.
    for kind, alpha, density in itertools.product((1, 2, 3), (0., .37, 1.), (0., .25, 1.)):
        values = [[.2, .65, .9, alpha], [.7, .3, .4, .6], [.1, .8, .25, .75]]
        color = (values[0][:3] if kind == 1 else
                 [a * b for a, b in zip(values[0][:3], values[1])])
        if kind == 3:
            color = [min(1., c + d) for c, d in zip(color, values[2])]
        result_alpha = alpha * .6 if kind == 2 else alpha
        fog = [.12, .34, .56, density]
        expected = [c * (1. - density) + f * density for c, f in zip(color, fog)] + [result_alpha]
        yield dict(name=f'kind-{kind}-alpha-{alpha}-fog-{density}', kind=kind,
                   inputs=values, fog=fog, expected=expected)


NATIVE_RUNNER = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cmath>
#include <cstdio>
struct SkyVertex { float x,y,z,u,v,lu,lv; };
struct SkyFrame { simd_float4x4 vp; simd_float4 cameraExposure, planarFog; };
struct SkyMaterial { uint32_t kind,pad[3];simd_float4 scale01,scale2,offset01,offset2; };
static_assert(sizeof(SkyVertex)==28,"Shared sky vertex ABI");
static_assert(sizeof(SkyFrame)==96,"Sky frame ABI");
static_assert(sizeof(SkyMaterial)==80,"Sky material ABI");
static bool near(float actual,float expected,float tolerance=0.000003f) {
    return std::isfinite(actual) && fabsf(actual-expected)<=tolerance;
}
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=3)return 2;
    NSError *error=nil;
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();
    if(!device){fprintf(stderr,"No Metal device\n");return 77;}
    NSString *source=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
                                              encoding:NSUTF8StringEncoding error:&error];
    source=[source stringByAppendingString:@"\nkernel void validate_sky(constant float4 *v [[buffer(0)]],constant uint &kind [[buffer(1)]],device float4 *out [[buffer(2)]]) { out[0]=sky_apply_planar_fog(sky_combine(v[0],v[1],v[2],kind),v[3]); out[1]=float4(sky_world_position(v[4].xyz,v[5].xyz),1); }\n"];
    MTLCompileOptions *options=[MTLCompileOptions new];options.fastMathEnabled=NO;
    id<MTLLibrary> library=[device newLibraryWithSource:source options:options error:&error];
    if(!library){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 1;}
    id<MTLComputePipelineState> compute=[device newComputePipelineStateWithFunction:
        [library newFunctionWithName:@"validate_sky"] error:&error];
    if(!compute)return 3;
    NSArray *cases=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:
        [NSString stringWithUTF8String:argv[2]]] options:0 error:&error];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    unsigned passed=0;float maxError=0;
    for(NSDictionary *fixture in cases) {
        simd_float4 values[6];
        for(unsigned i=0;i<3;i++)for(unsigned c=0;c<4;c++)values[i][c]=[fixture[@"inputs"][i][c] floatValue];
        for(unsigned c=0;c<4;c++)values[3][c]=[fixture[@"fog"][c] floatValue];
        values[4]={102400,-51200,25600,0};values[5]={120,-182,55,0};
        uint32_t kind=[fixture[@"kind"] unsignedIntValue];
        id<MTLBuffer> output=[device newBufferWithLength:32 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:compute];[encoder setBytes:values length:sizeof(values) atIndex:0];
        [encoder setBytes:&kind length:4 atIndex:1];[encoder setBuffer:output offset:0 atIndex:2];
        [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 4;
        float *actual=(float *)output.contents;
        for(unsigned c=0;c<4;c++) {
            float expected=[fixture[@"expected"][c] floatValue],difference=fabsf(actual[c]-expected);
            maxError=fmaxf(maxError,difference);
            if(!near(actual[c],expected)) {
                fprintf(stderr,"%s channel%u actual%.9g expected%.9g\n",
                        [fixture[@"name"] UTF8String],c,actual[c],expected);return 5;
            }
        }
        const float expectedPosition[4]={219.8828125f,-231.822265625f,79.9462890625f,1};
        for(unsigned c=0;c<4;c++)if(!near(actual[4+c],expectedPosition[c],0.00003f))return 6;
        passed++;
    }
    // Exercise actual vertex/fragment bindings and fixed-function blending.
    // Transparent moon texels retain the background; RGB writes preserve alpha.
    MTLRenderPipelineDescriptor *desc=[MTLRenderPipelineDescriptor new];
    desc.vertexFunction=[library newFunctionWithName:@"sky_vertex"];
    desc.fragmentFunction=[library newFunctionWithName:@"sky_fragment"];
    desc.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
    desc.colorAttachments[0].blendingEnabled=YES;
    desc.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorSourceAlpha;
    desc.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
    desc.colorAttachments[0].writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;
    id<MTLRenderPipelineState> render=[device newRenderPipelineStateWithDescriptor:desc error:&error];
    if(!render){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 7;}
    const SkyVertex vertices[4]={{-1024,-1024,0,0,0,0,0},{1024,-1024,0,1,0,0,0},
                               {-1024,1024,0,0,1,0,0},{1024,1024,0,1,1,0,0}};
    SkyFrame frame={matrix_identity_float4x4,{0,0,0,1},{0,0,0,0}};
    unsigned compositions=0;
    for(unsigned kind=1;kind<=3;kind++)for(unsigned alpha: {0u,128u,255u}) {
        unsigned char bytes[3][4]={{64,128,192,(unsigned char)alpha},{192,64,128,128},{32,192,64,192}};
        id<MTLTexture> textures[3];
        for(unsigned i=0;i<3;i++) {
            MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
                MTLPixelFormatRGBA8Unorm width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;
            textures[i]=[device newTextureWithDescriptor:td];
            [textures[i] replaceRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0 withBytes:bytes[i] bytesPerRow:4];
        }
        MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatRGBA32Float width:1 height:1 mipmapped:NO];td.storageMode=MTLStorageModeShared;
        td.usage=MTLTextureUsageRenderTarget;
        id<MTLTexture> target=[device newTextureWithDescriptor:td];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(.15,.25,.35,.83);
        SkyMaterial material={kind,{0,0,0},{1,1,1,1},{1,1,0,0},{},{}};
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        [encoder setRenderPipelineState:render];
        [encoder setVertexBytes:vertices length:sizeof(vertices) atIndex:0];
        [encoder setVertexBytes:&frame length:sizeof(frame) atIndex:1];
        [encoder setFragmentBytes:&frame length:sizeof(frame) atIndex:0];
        [encoder setFragmentBytes:&material length:sizeof(material) atIndex:1];
        for(unsigned i=0;i<3;i++)[encoder setFragmentTexture:textures[i] atIndex:i];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangleStrip vertexStart:0 vertexCount:4];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 8;
        float actual[4];[target getBytes:actual bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,1,1) mipmapLevel:0];
        float sourceAlpha=alpha/255.f*(kind==2?128/255.f:1.f),background[3]={.15,.25,.35};
        for(unsigned c=0;c<3;c++) {
            float color=bytes[0][c]/255.f;
            if(kind>=2)color*=bytes[1][c]/255.f;
            if(kind==3)color=fminf(1.f,color+bytes[2][c]/255.f);
            float expected=color*sourceAlpha+background[c]*(1-sourceAlpha);
            if(!near(actual[c],expected)) {fprintf(stderr,"Blend kind%u alpha%u ch%u actual%.9g expected%.9g\n",kind,alpha,c,actual[c],expected);return 9;}
        }
        if(!near(actual[3],.83f))return 10;
        compositions++;
    }
    printf("%u sky combiner/transform cases and %u alpha compositions passed; max float error %.9g\n",passed,compositions,maxError);
    return 0;
} }
'''


class SkyGpuTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang++'),
                         'Apple native Metal runtime is required')
    def test_sky_combiners_camera_transform_and_alpha_composition(self):
        with tempfile.TemporaryDirectory(prefix='halo-metal-sky-') as directory:
            folder = Path(directory)
            (folder / 'cases.json').write_text(json.dumps(list(sky_cases())))
            (folder / 'validate.mm').write_text(NATIVE_RUNNER)
            executable = folder / 'validate'
            subprocess.run(['clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra',
                            str(folder / 'validate.mm'), '-framework', 'Foundation', '-framework', 'Metal',
                            '-o', str(executable)], check=True, capture_output=True)
            result = subprocess.run([str(executable), str(ROOT / 'port/macos/metal-poc/Sky.metal'),
                                     str(folder / 'cases.json')], capture_output=True, text=True)
            if result.returncode == 77:
                self.skipTest(result.stderr.strip())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('27 sky combiner/transform cases and 9 alpha compositions passed', result.stdout)
            print(result.stdout.strip())


class SkyAssetTests(unittest.TestCase):
    @unittest.skipUnless(RETAIL_MAP.is_file(), 'User-owned Blood Gulch cache is unavailable')
    def test_original_sky_assets_and_supported_sampler_material_state(self):
        cache = Cache(RETAIL_MAP)
        _, scenario, _ = cache.tag(cache.u32(cache.tag_offset + 4))
        count, pointer = cache.unpack('<II', scenario + 0x30)
        self.assertEqual(count, 1)
        _, sky, _ = cache.tag(cache.u32(cache.pointer(pointer) + 12))
        self.assertEqual(cache.u32(sky + 0xb8), 0)  # no model animation
        _, model, _ = cache.tag(cache.u32(sky + 12))
        region_count, _ = cache.unpack('<II', model + 0xc4)
        self.assertEqual(region_count, 5)
        shader_count, shader_pointer = cache.unpack('<II', model + 0xdc)
        shaders = cache.pointer(shader_pointer)
        self.assertEqual(shader_count, 5)
        for index in range(shader_count):
            cls, shader, _ = cache.tag(cache.u32(shaders + index * 32 + 12))
            self.assertIn(cls, ('sotr', 'schi'))
            self.assertEqual(cache.span(shader + 0x29, 1), b'\0')
            self.assertEqual(cache.unpack('<4H', shader + 0x2a), (0, 0, 0, 0))
            self.assertEqual(cache.u32(shader + 0x48), 0)  # no extra layers
            maps, map_pointer = cache.unpack('<II', shader + 0x54)
            for mi in range(maps):
                offset = cache.pointer(map_pointer) + mi * (100 if cls == 'sotr' else 220)
                self.assertEqual(cache.unpack('<H', offset)[0], 0)  # linear + repeat, no alpha replicate
        with tempfile.TemporaryDirectory(prefix='halo-sky-assets-') as directory:
            folder = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                manifest = export(RETAIL_MAP, folder)
            self.assertEqual([m['kind'] for m in manifest['sky_meshes']], [3, 1, 1, 1, 2])
            for mesh in manifest['sky_meshes'][1:4]:
                texture = manifest['textures'][mesh['textures'][0]]
                self.assertEqual(texture['source_format'], 15)  # original DXT3 planet/ring RGBA
                alpha = (folder / texture['file']).read_bytes()[3::4]
                self.assertEqual((min(alpha), max(alpha)), (0, 255))


if __name__ == '__main__':
    unittest.main()
