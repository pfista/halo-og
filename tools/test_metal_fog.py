#!/usr/bin/env python3
"""Validate the atmospheric helper against Halo's packed fog pass on Metal."""
import json
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
COLOR = [1., 230 / 255, 196 / 255]


def clamp(x, low=0., high=1.):
    return min(high, max(low, x))


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def packed_fog_pass(texel, density, color, background):
    """Independent interpreter of fog.c:660-684 with planar fog disabled.

    Both alpha and RGB portions read before either writes. Constants are
    packed UNORM8 values, matching real_*_to_pixel32 in the original pass.
    """
    registers = {i: [0.] * 4 for i in range(16)}
    registers[8] = [texel] * 4
    registers[9] = [.7, .7, .7, .3]  # Its contribution cancels with planar density zero.
    constants = [([density] * 3 + [0.], [0.] * 4), (color + [0.], [1.] * 4)]
    rgb_inputs = [0x11180118, 0x0108021C]
    alpha_inputs = [0x02191209, 0x283C311C]
    rgb_outputs = [0x48, 0xCD]
    alpha_outputs = [0xC00, 0xCD]

    def read(input_byte, alpha, final=False):
        value = registers[input_byte & 15]
        if alpha:
            values = [value[3 if input_byte & 16 else 2]]
        elif input_byte & 16:
            values = [value[3]] * 3
        else:
            values = value[:3]
        if (input_byte & 0xe0) == 0x20:
            return [1. - clamp(x) for x in values]
        assert (input_byte & 0xe0) == 0
        return [max(0., x) for x in values]

    for stage in range(2):
        registers[1], registers[2] = constants[stage]
        writes = []
        for alpha, inputs, outputs in ((False, rgb_inputs[stage], rgb_outputs[stage]),
                                       (True, alpha_inputs[stage], alpha_outputs[stage])):
            a, b, c, d = [read((inputs >> shift) & 255, alpha) for shift in (24, 16, 8, 0)]
            ab = [clamp(x * y, -1., 1.) for x, y in zip(a, b)]
            cd = [clamp(x * y, -1., 1.) for x, y in zip(c, d)]
            for register, value in (((outputs >> 4) & 15, ab), (outputs & 15, cd),
                                    ((outputs >> 8) & 15, [clamp(x+y, -1., 1.) for x,y in zip(ab,cd)])):
                if register:
                    writes.append((register, alpha, value))
        for register, alpha, value in writes:
            if alpha:
                registers[register][3] = value[0]
            else:
                registers[register][:3] = value
    ef = [x*y for x,y in zip(read(0x0D, False, True), read(0x24, False, True))]
    registers[15][:3] = ef
    a, b, c, d = [read(value, False, True) for value in (0x0C, 0x3D, 0x00, 0x0F)]
    premultiplied = [clamp(x*y + (1.-x)*z + w) for x,y,z,w in zip(a,b,c,d)]
    alpha = clamp(read(0x3C, True, True)[0])
    return [clamp(source + clamp(destination)*(1.-alpha))
            for source,destination in zip(premultiplied,background)] + [alpha]


def fog_cases():
    cases = []
    cameras = [('spawn', [98.49340057373047, -157.63900756835938, 3.2047300338745117],
                1.328281044960022, 0.), ('overview', [120., -182., 55.], 2.18, -.5)]
    for name, camera, yaw, pitch in cameras:
        forward = [f32(math.cos(yaw)*math.cos(pitch)), f32(math.sin(yaw)*math.cos(pitch)), f32(math.sin(pitch))]
        right = [math.sin(yaw), -math.cos(yaw), 0.]
        start, end = 3., 100.
        plane = [f32(x/(end-start)) for x in forward]
        plane += [f32(-(start+sum(x*y for x,y in zip(camera, forward)))/(end-start))]
        for distance, lateral in [(-10., 0.), (0., 0.), (3., 0.), (6.03125, 0.),
                                  (12.09375, 0.), (20., 0.), (20., 500.), (51.5, 0.),
                                  (96.96875, 0.), (100., 0.), (300., 0.)]:
            point = [f32(c+d*distance+r*lateral) for c,d,r in zip(camera,forward,right)]
            coordinate = sum(x*y for x,y in zip(point,plane[:3])) + plane[3]
            # Original 16x16 AY8 lookup rows are byte ramp0,17,...255.
            # GL/Metal normalized linear filtering: x=16*u-.5, clamp to edge.
            texel = clamp((coordinate*16.-.5)/15.)
            background = [.2, .4, .8]
            cases.append(dict(name=f'{name}-distance-{distance}-lateral-{lateral}',
                              point=point+[1.], base=background+[1.], plane=plane,
                              color_density=COLOR+[.4],
                              expected=packed_fog_pass(texel, .4, COLOR, background)))
    # Texel centers exercise every authored lookup value without approximation.
    for i in range(16):
        coordinate = (i+.5)/16.
        background = [.8, .6, .2]
        cases.append(dict(name=f'lookup-texel-center-{i}', point=[coordinate,0.,0.,1.],
                          base=background+[1.], plane=[1.,0.,0.,0.], color_density=COLOR+[.4],
                          expected=packed_fog_pass(i/15.,.4,COLOR,background)))
    for name, density, background in [('disabled',0.,[.2,.4,.8]), ('opaque',1.,[.2,.4,.8]),
                                       ('framebuffer-clamp',.4,[-1.,2.,.5])]:
        cases.append(dict(name=name, point=[1.,0.,0.,1.],base=background+[1.],
                          plane=[1.,0.,0.,0.],color_density=COLOR+[density],
                          expected=packed_fog_pass(1.,density,COLOR,background)))
    return cases


NATIVE_RUNNER = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cmath>
#include <cstdio>
struct FogCase { simd_float4 point, base, plane, colorDensity; };
static_assert(sizeof(FogCase)==64,"Fog fixture ABI");
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=3)return 2;
    NSError *error=nil;
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();
    if(!device){fprintf(stderr,"No Metal device\n");return 77;}
    NSString *source=[NSString stringWithContentsOfFile:@(argv[1]) encoding:NSUTF8StringEncoding error:&error];
    source=[source stringByAppendingString:@R"(
struct FogCase { float4 point,base; AtmosphericFogUniforms fog; };
kernel void validate_fog(constant FogCase &fixture [[buffer(0)]], device float4 *out [[buffer(1)]],
                        texture2d<float> density [[texture(0)]]) {
    float coordinate=atmospheric_fog_coordinate(fixture.point.xyz,fixture.fog);
    out[0]=float4(apply_atmospheric_fog(fixture.base.rgb,coordinate,density,fixture.fog),
                 atmospheric_fog_amount(coordinate,density,fixture.fog));
}
)"];
    MTLCompileOptions *options=[MTLCompileOptions new];
    options.fastMathEnabled=NO; options.preserveInvariance=YES;
    id<MTLLibrary> library=[device newLibraryWithSource:source options:options error:&error];
    if(!library){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 1;}
    id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:
        [library newFunctionWithName:@"validate_fog"] error:&error];
    if(!pipeline)return 3;
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
        width:16 height:16 mipmapped:NO];td.storageMode=MTLStorageModeShared;td.usage=MTLTextureUsageShaderRead;
    id<MTLTexture> density=[device newTextureWithDescriptor:td];
    uint8_t bytes[16*16*4];
    for(unsigned y=0;y<16;y++)for(unsigned x=0;x<16;x++)for(unsigned c=0;c<4;c++)bytes[(y*16+x)*4+c]=x*17;
    [density replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:bytes bytesPerRow:64];
    NSArray *cases=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])]
        options:0 error:&error];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    unsigned passed=0; float maxError=0;
    for(NSDictionary *fixture in cases) {
        FogCase input;
        simd_float4 *fields[]={&input.point,&input.base,&input.plane,&input.colorDensity};
        NSString *keys[]={@"point",@"base",@"plane",@"color_density"};
        for(unsigned f=0;f<4;f++)for(unsigned c=0;c<4;c++)(*fields[f])[c]=[fixture[keys[f]][c] floatValue];
        id<MTLBuffer> result=[device newBufferWithLength:16 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];[encoder setBytes:&input length:sizeof(input) atIndex:0];
        [encoder setBuffer:result offset:0 atIndex:1];[encoder setTexture:density atIndex:0];
        [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 4;
        float *actual=(float *)result.contents;
        for(unsigned c=0;c<4;c++) {
            float expected=[fixture[@"expected"][c] floatValue],difference=fabsf(actual[c]-expected);
            maxError=fmaxf(maxError,difference);
            // Texel centers/endpoints use tight arithmetic comparison. Native
            // UNORM linear filtering has finite subtexel precision off-center;
            // permit less than 1/64 of one 8-bit channel there.
            bool exact=[fixture[@"name"] hasPrefix:@"lookup-"] ||
                [fixture[@"name"] isEqualToString:@"disabled"] ||
                [fixture[@"name"] isEqualToString:@"opaque"] ||
                [fixture[@"name"] isEqualToString:@"framebuffer-clamp"];
            float tolerance=exact ? 0.000003f : 1.0f/(255.0f*64.0f);
            if(!std::isfinite(actual[c]) || difference>tolerance) {
                fprintf(stderr,"%s channel%u actual%.9g expected%.9g\n",[fixture[@"name"] UTF8String],c,actual[c],expected);return 5;
            }
        }
        passed++;
    }
    printf("%u original packed-fog cases passed on %s; max float error %.9g\n",passed,device.name.UTF8String,maxError);
    return 0;
} }
'''


class AtmosphericFogTests(unittest.TestCase):
    def test_ay8_luminance_alpha_and_authored_layout(self):
        from metal_poc_export import decode_bitmap, decode_bitmap_mipmaps
        values = bytes([0, 17, 34, 255, 85, 102, 119, 136])
        expected = bytes(channel for value in values for channel in [value] * 4)
        self.assertEqual(decode_bitmap(values, 4, 2, 2, False), expected)
        # Independent 4x2 Morton arrangement. The 1x1 authored level must
        # retain its own value rather than being regenerated from mip0.
        swizzled = bytes(values[index] for index in (0, 1, 4, 5, 2, 3, 6, 7))
        levels = decode_bitmap_mipmaps(swizzled + bytes([153, 170, 187]), 4, 2, 2, 9, 2)
        self.assertEqual([(m['width'], m['height']) for m in levels], [(4, 2), (2, 1), (1, 1)])
        self.assertEqual(levels[0]['rgba'], expected)
        self.assertEqual(levels[1]['rgba'], bytes([153] * 4 + [170] * 4))
        self.assertEqual(levels[2]['rgba'], bytes([187] * 4))
        padded = values[:4] + bytes(60) + values[4:] + bytes(60)
        self.assertEqual(decode_bitmap_mipmaps(padded, 4, 2, 2, 16, 0)[0]['rgba'], expected)
        with self.assertRaisesRegex(ValueError, 'Truncated bitmap mip chain'):
            decode_bitmap_mipmaps(swizzled + bytes([153, 170]), 4, 2, 2, 9, 2)

    def test_stock_cache_lookup_and_outdoor_parameters(self):
        from metal_poc_export import Cache, export
        path=ROOT.parent/'pfista-halo-macos/assets/maps/bloodgulch.map'
        if not path.exists():self.skipTest('User-owned stock Blood Gulch cache is not available')
        cache=Cache(path)
        if cache.sha256!='50fe52406f075d975e24100a65b26ff696458023dd3509878953052ab0ef858f':
            self.skipTest('Stock reference Blood Gulch cache is not available')
        cls,bitmap,name=cache.tag(0xe6f80584)
        self.assertEqual((cls,name),('bitm','rasterizer\\atmospheric fog density'))
        count,pointer=cache.unpack('<II',bitmap+96)
        data=cache.pointer(pointer,count*48)
        self.assertEqual(cache.unpack('<6H',data+4),(16,16,1,0,2,137))
        self.assertEqual(cache.unpack('<h',data+20)[0],0)
        raw=cache.span(cache.u32(data+24),cache.u32(data+28))
        # This exact 4-bit Morton interleave independently checks the authored
        # AY8 density data, not the preview's exported decode.
        for y in range(16):
            for x in range(16):
                address=sum(((x>>bit)&1)<<(bit*2) | ((y>>bit)&1)<<(bit*2+1) for bit in range(4))
                self.assertEqual(raw[address],x*17)
        _, scenario, _ = cache.tag(cache.u32(cache.tag_offset + 4))
        sky_count, sky_pointer = cache.unpack('<II', scenario + 0x30)
        self.assertEqual(sky_count, 1)
        sky_id = cache.u32(cache.pointer(sky_pointer, 16) + 12)
        _,sky,_=cache.tag(sky_id)
        for actual,expected in zip(cache.unpack('<3f',sky+0x58),COLOR):self.assertAlmostEqual(actual,expected,places=5)
        for actual,expected in zip(cache.unpack('<3f',sky+0x6c),(.4,3.,100.)):self.assertAlmostEqual(actual,expected,places=5)
        with tempfile.TemporaryDirectory(prefix='halo-metal-fog-export-test-') as directory:
            folder = Path(directory)
            export(path, folder)
            scene = json.loads((folder / 'scene.json').read_text())
            fog = scene['fog']
            self.assertEqual(scene['clear_color'], COLOR)
            self.assertEqual(fog['color'], COLOR)
            self.assertEqual((fog['density'], fog['start'], fog['end'], fog['enabled'], fog['planar_mode']),
                             (.4, 3., 100., True, 0))
            self.assertEqual(fog['source_sky'], 'levels\\test\\bloodgulch\\bloodgulch')
            self.assertEqual(fog['source_density'], cache.unpack('<f', sky + 0x6c)[0])
            texture = scene['textures'][fog['density_texture']]
            self.assertEqual((texture['width'], texture['height'], texture['source_format'], texture['swizzled']),
                             (16, 16, 2, True))
            self.assertEqual(texture['mipmaps'], [dict(file=texture['file'], width=16, height=16)])
            rgba = (folder / texture['file']).read_bytes()
            self.assertEqual(rgba, bytes(channel for y in range(16) for x in range(16)
                                         for channel in [x * 17] * 4))

    def test_packed_pass_has_expected_half_density_color(self):
        for actual, expected in zip(packed_fog_pass(.5,.4,[1.,.5,.25],[.2,.4,.8]),[.36,.42,.69,.2]):
            self.assertAlmostEqual(actual,expected)

    def test_disabled_and_opaque_packed_pass(self):
        self.assertEqual(packed_fog_pass(1.,0.,COLOR,[.2,.4,.8]),[.2,.4,.8,0.])
        self.assertEqual(packed_fog_pass(1.,1.,COLOR,[.2,.4,.8]),COLOR+[1.])

    @unittest.skipUnless(sys.platform=='darwin' and shutil.which('clang++'), 'Apple Metal runtime')
    def test_native_lookup_projection_clamping_and_packed_blend(self):
        with tempfile.TemporaryDirectory(prefix='halo-metal-fog-') as directory:
            folder=Path(directory);cases=list(fog_cases())
            (folder/'cases.json').write_text(json.dumps(cases));(folder/'validate.mm').write_text(NATIVE_RUNNER)
            executable=folder/'validate'
            subprocess.run(['clang++','-std=c++17','-O2','-fobjc-arc',str(folder/'validate.mm'),
                            '-framework','Foundation','-framework','Metal','-o',str(executable)],
                           check=True,capture_output=True)
            result=subprocess.run([str(executable),str(ROOT/'port/macos/metal-poc/Fog.metal'),str(folder/'cases.json')],
                                  capture_output=True,text=True)
            if result.returncode==77:self.skipTest(result.stderr.strip())
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(f'{len(cases)} original packed-fog cases passed',result.stdout)
            print(result.stdout.strip())


if __name__=='__main__':
    unittest.main()
