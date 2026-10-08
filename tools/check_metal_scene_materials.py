#!/usr/bin/env python3
"""Opt-in check of the preview's environment combiners on native Metal."""
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def material_cases():
    base = [.2, .65, .9, .25]
    primary = [.7, .3, .4, .6]
    secondary = [.1, .8, .25, .75]
    micro = [.4, .7, .2, .8]
    settings = list(itertools.product(range(3), range(3), range(3)))
    for shader_type, detail_function, micro_function in settings:
        # Each equation comes from the Xbox packed combiner state in
        # rasterizer_xbox_environment.c:1616-1706, not emitted shader text.
        weight = secondary[3] if shader_type == 0 else base[3]
        combined = [s*(1-weight)+p*weight for s, p in zip(secondary[:3], primary)]
        color = []
        for b, d, m in zip(base[:3], combined, micro):
            first = (2*b*d, b*d, b+2*d-1)[detail_function]
            first = min(1., max(0., first))
            final = (2*first*m, first*m, first+2*m-1)[micro_function]
            color.append(min(1., max(0., final)))
        alpha = (base[3]*((1-secondary[3])*secondary[3]+secondary[3]*primary[3]),
                 secondary[3]*(1-base[3])+primary[3]*base[3], base[3])[shader_type]*micro[3]
        yield dict(name=f'type-{shader_type}-detail-{detail_function}-micro-{micro_function}',
                   material=[shader_type, detail_function, micro_function],
                   input=[base, primary, secondary, micro], expected=color+[alpha])
    # End-point masks isolate primary versus secondary, independently of
    # detail blending; neutral micro and multiplication retain exact colors.
    for shader_type, mask in itertools.product(range(3), (0., 1.)):
        b, p, s, m = base[:], primary[:], secondary[:], [.5]*3+[1.]
        b[:3] = [1.]*3
        if shader_type == 0:
            s[3] = mask
        else:
            b[3] = mask
        alpha = (b[3]*((1-s[3])*s[3]+s[3]*p[3]),
                 s[3]*(1-b[3])+p[3]*b[3], b[3])[shader_type]
        yield dict(name=f'mask-endpoint-type-{shader_type}-{mask}',
                   material=[shader_type, 1, 0], input=[b, p, s, m],
                   expected=(p if mask else s)[:3]+[alpha])


NATIVE_RUNNER = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cstdio>
#include <cmath>
struct Material { uint32_t alpha, type, detail, micro; simd_float4 scale01,scale2; };
static_assert(sizeof(Material)==48,"Material uniform ABI");
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=3)return 2;
    NSError *error=nil;
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();
    if(!device){fprintf(stderr,"No Metal device\n");return 77;}
    NSString *source=[NSString stringWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]
                                              encoding:NSUTF8StringEncoding error:&error];
    source=[source stringByAppendingString:@"\nkernel void validate_material(constant float4 *v [[buffer(0)]], constant MaterialUniforms &m [[buffer(1)]], device float4 *out [[buffer(2)]]) { out[0]=environment_diffuse(v[0],v[1],v[2],v[3],m); }\n"];
    MTLCompileOptions *options=[MTLCompileOptions new];options.fastMathEnabled=NO;
    id<MTLLibrary> library=[device newLibraryWithSource:source options:options error:&error];
    if(!library){fprintf(stderr,"%s\n",error.localizedDescription.UTF8String);return 1;}
    id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:
        [library newFunctionWithName:@"validate_material"] error:&error];
    if(!pipeline)return 3;
    NSData *data=[NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]];
    NSArray *cases=[NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
    id<MTLCommandQueue> queue=[device newCommandQueue];
    unsigned passed=0;float maxError=0;
    for(NSDictionary *fixture in cases) {
        simd_float4 values[4];
        for(unsigned i=0;i<4;i++)for(unsigned c=0;c<4;c++)values[i][c]=[fixture[@"input"][i][c] floatValue];
        NSArray *settings=fixture[@"material"];
        Material m={0,[settings[0] unsignedIntValue],[settings[1] unsignedIntValue],[settings[2] unsignedIntValue],{},{}};
        id<MTLBuffer> result=[device newBufferWithLength:16 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];[encoder setBytes:values length:sizeof(values) atIndex:0];
        [encoder setBytes:&m length:sizeof(m) atIndex:1];[encoder setBuffer:result offset:0 atIndex:2];
        [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted)return 4;
        float *actual=(float *)result.contents;
        for(unsigned c=0;c<4;c++) {
            float expected=[fixture[@"expected"][c] floatValue],difference=fabsf(actual[c]-expected);
            maxError=fmaxf(maxError,difference);
            if(!std::isfinite(actual[c]) || difference>0.000002f) {
                fprintf(stderr,"%s channel%u actual%.9g expected%.9g\n",
                        [fixture[@"name"] UTF8String],c,actual[c],expected);return 5;
            }
        }
        passed++;
    }
    printf("%u material cases passed; max float error %.9g\n",passed,maxError);return 0;
} }
'''


class EnvironmentMaterialTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang++'),
                         'Apple native Metal runtime is required')
    def test_original_blend_functions_masks_and_specular_alpha(self):
        with tempfile.TemporaryDirectory(prefix='halo-scene-materials-') as directory:
            folder = Path(directory)
            (folder/'cases.json').write_text(json.dumps(list(material_cases())))
            (folder/'validate.mm').write_text(NATIVE_RUNNER)
            # The viewer compiles its original atmospheric helper before the
            # environment shader. Keep the material-only kernel on that same
            # source path when Scene gains its fragment fog call.
            shader = folder / 'Scene.metal'
            shader.write_text((ROOT/'port/macos/metal-poc/Fog.metal').read_text() + '\n' +
                              (ROOT/'port/macos/metal-poc/Scene.metal').read_text())
            executable = folder/'validate'
            subprocess.run(['clang++', '-std=c++17', '-O2', '-fobjc-arc', '-Wall', '-Wextra',
                            str(folder/'validate.mm'), '-framework', 'Foundation', '-framework', 'Metal',
                            '-o', str(executable)], check=True, capture_output=True)
            result = subprocess.run([str(executable), str(shader),
                                     str(folder/'cases.json')], capture_output=True, text=True)
            if result.returncode == 77:
                self.skipTest(result.stderr.strip())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('33 material cases passed', result.stdout)
            print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
