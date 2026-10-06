// Source-only GPU validation of the native Xbox shader emitters. No game,
// SDL, OpenGL, ANGLE, map data or application installation is involved.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <CommonCrypto/CommonDigest.h>
#include <cstdio>
#include <vector>
#include <cmath>

struct PixelUniforms {
    simd_float4 ps_c0[8], ps_c1[8], ps_final_c0, ps_final_c1, fog_color, fog_parameters;
    float alpha_reference, depth_scale, depth_clip_min, depth_clip_max;
    simd_float4 bump_matrix[4], bump_luminance[4], texture_scale[4], texture_border_color[4];
    simd_float4 texture_lod_bias;
};
struct TestInputs { simd_float4 d0,d1,b0,b1,t[4]; float fog, padding[3]; };
static_assert(sizeof(PixelUniforms) == 608, "Metal pixel uniform ABI");
static_assert(sizeof(TestInputs) == 144, "Test input ABI");

static void require(bool ok, NSString *reason) {
    if (!ok) { fprintf(stderr,"metal-shaders: %s\n", reason.UTF8String); exit(1); }
}
static NSData *read(NSString *path) {
    NSError *e=nil; NSData *d=[NSData dataWithContentsOfFile:path options:0 error:&e];
    require(d!=nil,e.localizedDescription ?: path); return d;
}
static NSString *sha256(NSData *data) {
    require(data.length<=UINT32_MAX,@"Validation input too large");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes,(CC_LONG)data.length,digest);
    NSMutableString *out=[NSMutableString new];
    for(unsigned char byte:digest)[out appendFormat:@"%02x",byte];
    return out;
}
static id<MTLLibrary> library(id<MTLDevice> device, NSString *source, NSString *label) {
    NSError *e=nil; MTLCompileOptions *options=[MTLCompileOptions new];
    options.fastMathEnabled=NO;
    options.preserveInvariance=YES;
    id<MTLLibrary> lib=[device newLibraryWithSource:source options:options error:&e];
    require(lib!=nil,[NSString stringWithFormat:@"%@: %@",label,e.localizedDescription]); return lib;
}
static simd_float4 vector(NSArray *values) {
    require(values.count==4,@"Invalid fixture vector");
    return { [values[0] floatValue],[values[1] floatValue],[values[2] floatValue],[values[3] floatValue] };
}
static const char *testVertex = R"MSL(
#include <metal_stdlib>
using namespace metal;
struct Varyings {
 float4 position [[position]];
 float4 xD0 [[user(xD0)]],xD1 [[user(xD1)]],xB0 [[user(xB0)]],xB1 [[user(xB1)]];
 float4 xT0 [[user(xT0)]],xT1 [[user(xT1)]],xT2 [[user(xT2)]],xT3 [[user(xT3)]];
 float xFog [[user(xFog)]];
};
struct Inputs { float4 d0,d1,b0,b1,t[4]; float fog; float padding[3]; };
vertex Varyings test_vertex(uint id [[vertex_id]],constant Inputs &i [[buffer(0)]]) {
 float2 p=float2((id<<1)&2,id&2);
 Varyings o; o.position=float4(p*2-1,0.5,1);
 o.xD0=i.d0;o.xD1=i.d1;o.xB0=i.b0;o.xB1=i.b1;
 o.xT0=i.t[0];o.xT1=i.t[1];o.xT2=i.t[2];o.xT3=i.t[3];o.xFog=i.fog;return o;
}
)MSL";

int main(int argc,const char **argv) { @autoreleasepool {
    require(argc==2,@"Usage: shader_validate manifest.json");
    NSString *path=[NSString stringWithUTF8String:argv[1]], *root=path.stringByDeletingLastPathComponent;
    NSData *manifestData=read(path);
    NSError *manifestError=nil;
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:manifestData options:0 error:&manifestError];
    require([manifest isKindOfClass:NSDictionary.class],manifestError.localizedDescription ?: @"Invalid manifest");
    NSString *runnerHash=sha256(read([NSString stringWithUTF8String:argv[0]]));
    require([runnerHash isEqualToString:manifest[@"runner_sha256"]],@"GPU runner differs from prepared manifest");
    id<MTLDevice> device=MTLCreateSystemDefaultDevice(); require(device!=nil,@"No Metal device");
    id<MTLCommandQueue> queue=[device newCommandQueue]; require(queue!=nil,@"No Metal queue");
    NSMutableDictionary<NSString *,id<MTLLibrary>> *libraries=[NSMutableDictionary new];
    NSUInteger compiled=0,passed=0,discarded=0,depthCases=0; float maxError=0,maxDepthError=0;
    for (NSString *name in manifest[@"compile"]) {
        NSData *data=read([root stringByAppendingPathComponent:name]);
        require([sha256(data) isEqualToString:manifest[@"shader_sha256"][name]],@"Shader differs from prepared manifest");
        NSString *source=[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        libraries[name]=library(device,source,name); compiled++;
    }
    id<MTLLibrary> vl=library(device,[NSString stringWithUTF8String:testVertex],@"fixture vertex");
    NSMutableDictionary<NSString *,id<MTLRenderPipelineState>> *pipelines=[NSMutableDictionary new];
    id<MTLTexture> texture;
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:4 height:4 mipmapped:NO];
    td.usage=MTLTextureUsageRenderTarget; td.storageMode=MTLStorageModeShared;
    texture=[device newTextureWithDescriptor:td];require(texture!=nil,@"No output texture");
    MTLTextureDescriptor *depthDescriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float width:4 height:4 mipmapped:NO];
    depthDescriptor.usage=MTLTextureUsageRenderTarget;depthDescriptor.storageMode=MTLStorageModePrivate;
    id<MTLTexture> depthTexture=[device newTextureWithDescriptor:depthDescriptor];
    id<MTLBuffer> depthReadback=[device newBufferWithLength:1024 options:MTLResourceStorageModeShared];
    require(depthTexture!=nil && depthReadback!=nil,@"No fixture depth resources");
    for (NSDictionary *f in manifest[@"pixel_tests"]) {
        NSString *name=f[@"shader"]; id<MTLLibrary> fl=libraries[name];require(fl!=nil,name);
        bool meterBlend=f[@"meter_blend"]!=nil;
        bool textBlend=[f[@"text_blend"] boolValue];
        NSString *pipelineKey=[name stringByAppendingString:meterBlend?@":meter":textBlend?@":text":@":opaque"];
        id<MTLRenderPipelineState> pipeline=pipelines[pipelineKey];
        if (!pipeline) {
            MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
            pd.vertexFunction=[vl newFunctionWithName:@"test_vertex"];
            pd.fragmentFunction=[fl newFunctionWithName:@"xgpu_fragment"];
            pd.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
            if(meterBlend) {
                // The original HUD meter uses CONSTANTCOLOR/SRCALPHA for
                // both RGB and alpha; green coverage adjusts source alpha.
                auto color=pd.colorAttachments[0];color.blendingEnabled=YES;
                color.sourceRGBBlendFactor=color.sourceAlphaBlendFactor=MTLBlendFactorBlendColor;
                color.destinationRGBBlendFactor=color.destinationAlphaBlendFactor=MTLBlendFactorSourceAlpha;
            } else if(textBlend) {
                // Original text blends ordinary coverage alpha and writes
                // RGB only; the framebuffer's authored alpha is preserved.
                auto color=pd.colorAttachments[0];color.blendingEnabled=YES;
                color.sourceRGBBlendFactor=color.sourceAlphaBlendFactor=MTLBlendFactorSourceAlpha;
                color.destinationRGBBlendFactor=color.destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
                color.writeMask=MTLColorWriteMaskRed|MTLColorWriteMaskGreen|MTLColorWriteMaskBlue;
            }
            pd.depthAttachmentPixelFormat=MTLPixelFormatDepth32Float;
            NSError *e=nil;pipeline=[device newRenderPipelineStateWithDescriptor:pd error:&e];
            require(pipeline!=nil,e.localizedDescription);pipelines[pipelineKey]=pipeline;
        }
        TestInputs inputs={}; NSDictionary *in=f[@"inputs"];
        inputs.d0=vector(in[@"d0"]);inputs.d1=vector(in[@"d1"]);
        inputs.b0=vector(in[@"b0"]);inputs.b1=vector(in[@"b1"]);
        for (int s=0;s<4;s++)inputs.t[s]=vector(in[@"t"][s]);
        inputs.fog=[in[@"fog"] floatValue];
        PixelUniforms u={};NSDictionary *uniforms=f[@"uniforms"];
        for(int s=0;s<8;s++) { u.ps_c0[s]=vector(uniforms[@"c0"][s]);u.ps_c1[s]=vector(uniforms[@"c1"][s]); }
        u.ps_final_c0=vector(uniforms[@"final_c0"]);u.ps_final_c1=vector(uniforms[@"final_c1"]);
        u.fog_color=vector(uniforms[@"fog_color"]);u.fog_parameters=vector(uniforms[@"fog_parameters"]);
        u.alpha_reference=[uniforms[@"alpha_reference"] floatValue];
        u.depth_scale=[uniforms[@"depth_scale"] floatValue];
        u.depth_clip_min=[uniforms[@"depth_clip_min"] floatValue];
        u.depth_clip_max=[uniforms[@"depth_clip_max"] floatValue];
        for(int s=0;s<4;s++) {
            u.bump_matrix[s]=vector(uniforms[@"bump_matrix"][s]);
            u.bump_luminance[s]=vector(uniforms[@"bump_luminance"][s]);
            u.texture_scale[s]=vector(uniforms[@"texture_scale"][s]);
            u.texture_border_color[s]=vector(uniforms[@"texture_border_color"][s]);
        }
        u.texture_lod_bias=vector(uniforms[@"texture_lod_bias"]);
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=texture;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        simd_float4 clear=f[@"clear_color"]?vector(f[@"clear_color"]):simd_float4{-1,-1,-1,-1};
        pass.colorAttachments[0].clearColor=MTLClearColorMake(clear.x,clear.y,clear.z,clear.w);
        pass.depthAttachment.texture=depthTexture;
        pass.depthAttachment.loadAction=MTLLoadActionClear;pass.depthAttachment.storeAction=MTLStoreActionStore;
        pass.depthAttachment.clearDepth=f[@"clear_depth"]?[f[@"clear_depth"] doubleValue]:.9;
        id<MTLCommandBuffer> cmd=[queue commandBuffer];
        id<MTLRenderCommandEncoder> enc=[cmd renderCommandEncoderWithDescriptor:pass];
        [enc setRenderPipelineState:pipeline];[enc setVertexBytes:&inputs length:sizeof(inputs) atIndex:0];
        if(meterBlend) {
            simd_float4 tint=vector(f[@"meter_blend"]);
            [enc setBlendColorRed:tint.x green:tint.y blue:tint.z alpha:tint.w];
        }
        MTLDepthStencilDescriptor *ds=[MTLDepthStencilDescriptor new];
        ds.depthWriteEnabled=f[@"depth_write"]?[f[@"depth_write"] boolValue]:YES;
        ds.depthCompareFunction=[f[@"depth_compare"] isEqual:@"less"]?MTLCompareFunctionLess:MTLCompareFunctionAlways;
        [enc setDepthStencilState:[device newDepthStencilStateWithDescriptor:ds]];
        [enc setFragmentBytes:&u length:sizeof(u) atIndex:0];
        NSMutableArray *resources=[NSMutableArray new];
        for(int s=0;s<4;s++) {
            NSDictionary *t=f[@"textures"][s]; int kind=[t[@"kind"] intValue];
            if (!kind)continue;
            NSUInteger width=[t[@"width"] unsignedIntegerValue],height=[t[@"height"] unsignedIntegerValue];
            NSUInteger depth=kind==2?[t[@"depth"] unsignedIntegerValue]:1;
            require(kind>=1 && kind<=3 && width && height && depth,@"Fixture texture dimensions/type");
            require(kind!=3 || width==height,@"Fixture cube must be square");
            NSArray *mips=t[@"mipmaps"] ?: @[t];
            require(mips.count==1 || kind==1,@"Mipped fixture requires texture2d");
            MTLTextureDescriptor *d=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:width height:height mipmapped:mips.count>1];
            d.mipmapLevelCount=mips.count;
            if(kind==2) { d.textureType=MTLTextureType3D;d.depth=depth; }
            else if(kind==3)d.textureType=MTLTextureTypeCube;
            d.usage=MTLTextureUsageShaderRead;d.storageMode=MTLStorageModeShared;
            id<MTLTexture> sample=[device newTextureWithDescriptor:d]; require(sample!=nil,@"Fixture texture");
            for(NSUInteger level=0;level<mips.count;level++) {
            NSDictionary *mip=mips[level];
            NSUInteger mipWidth=MAX((NSUInteger)1,width>>level),mipHeight=MAX((NSUInteger)1,height>>level);
            NSArray *faces=kind==3?mip[@"faces"]:@[mip[@"rgba"]];
            require(faces.count==(kind==3?6u:1u),@"Fixture cube face count");
            for(NSUInteger face=0;face<faces.count;face++) {
                NSArray *bytes=faces[face];std::vector<uint8_t> pixels;
                for(NSNumber *b in bytes) {
                    require([b isKindOfClass:NSNumber.class] && b.doubleValue==b.unsignedCharValue,@"Fixture texel byte");
                    pixels.push_back(b.unsignedCharValue);
                }
                require(pixels.size()==mipWidth*mipHeight*depth*4,@"Fixture texture bytes");
                [sample replaceRegion:MTLRegionMake3D(0,0,0,mipWidth,mipHeight,depth) mipmapLevel:level
                    slice:face withBytes:pixels.data() bytesPerRow:mipWidth*4 bytesPerImage:mipWidth*mipHeight*4];
            }
            }
            MTLSamplerDescriptor *sd=[MTLSamplerDescriptor new];
            bool linear=[t[@"linear"] boolValue];sd.minFilter=sd.magFilter=linear?MTLSamplerMinMagFilterLinear:MTLSamplerMinMagFilterNearest;
            unsigned axes=[t[@"clamp_axes"] unsignedIntValue];
            sd.sAddressMode=(axes&1)?MTLSamplerAddressModeClampToEdge:MTLSamplerAddressModeRepeat;
            sd.tAddressMode=(axes&2)?MTLSamplerAddressModeClampToEdge:MTLSamplerAddressModeRepeat;
            sd.rAddressMode=(axes&4)?MTLSamplerAddressModeClampToEdge:MTLSamplerAddressModeRepeat;
            unsigned borderAxes=[t[@"native_border_axes"] unsignedIntValue];
            if(borderAxes&1)sd.sAddressMode=MTLSamplerAddressModeClampToBorderColor;
            if(borderAxes&2)sd.tAddressMode=MTLSamplerAddressModeClampToBorderColor;
            sd.mipFilter=mips.count>1?([t[@"trilinear"] boolValue]?MTLSamplerMipFilterLinear:MTLSamplerMipFilterNearest):MTLSamplerMipFilterNotMipmapped;
            if(t[@"lod"])sd.lodMinClamp=sd.lodMaxClamp=[t[@"lod"] floatValue];
            id<MTLSamplerState> sampler=[device newSamplerStateWithDescriptor:sd];
            [enc setFragmentTexture:sample atIndex:s];[enc setFragmentSamplerState:sampler atIndex:s];
            [resources addObject:sample];[resources addObject:sampler];
            if(t[@"alpha_border_companion"]) {
                require(kind==1 && borderAxes,@"Alpha border companion requires bordered texture2d");
                sd.borderColor=MTLSamplerBorderColorOpaqueBlack;
                id<MTLSamplerState> companion=[device newSamplerStateWithDescriptor:sd];
                [enc setFragmentSamplerState:companion atIndex:4+s];[resources addObject:companion];
            }
        }
        [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[enc endEncoding];
        if(f[@"expected_depth"]) {
            id<MTLBlitCommandEncoder> blit=[cmd blitCommandEncoder];
            [blit copyFromTexture:depthTexture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                sourceSize:MTLSizeMake(4,4,1) toBuffer:depthReadback destinationOffset:0
                destinationBytesPerRow:256 destinationBytesPerImage:1024 options:MTLBlitOptionNone];
            [blit endEncoding];
        }
        [cmd commit];[cmd waitUntilCompleted];require(cmd.status==MTLCommandBufferStatusCompleted,cmd.error.localizedDescription);
        float actual[4];[texture getBytes:actual bytesPerRow:16 fromRegion:MTLRegionMake2D(2,2,1,1) mipmapLevel:0];
        bool discard=[f[@"discard"] boolValue];
        float tolerance=f[@"float_tolerance"]?[f[@"float_tolerance"] floatValue]:.00002f;
        require(std::isfinite(tolerance) && tolerance>0 && tolerance<=1.0f/255,@"Invalid fixture float tolerance");
        for(int c=0;c<4;c++) {
            float expected=discard?clear[c]:[f[@"expected"][c] floatValue];
            float error=fabsf(actual[c]-expected);maxError=fmaxf(maxError,error);
            require(std::isfinite(actual[c]) && error<tolerance,
                [NSString stringWithFormat:@"%@: channel %d actual %.9g expected %.9g",f[@"name"],c,actual[c],expected]);
        }
        if(f[@"expected_depth"]) {
            float actualDepth=((float *)depthReadback.contents)[2*64+2];
            float expectedDepth=[f[@"expected_depth"] floatValue],error=fabsf(actualDepth-expectedDepth);
            maxError=fmaxf(maxError,error);
            maxDepthError=fmaxf(maxDepthError,error);depthCases++;
            require(std::isfinite(actualDepth) && error<.00002f,
                [NSString stringWithFormat:@"%@: depth actual %.9g expected %.9g",f[@"name"],actualDepth,expectedDepth]);
        }
        passed++;if(discard)discarded++;
    }
    NSDictionary *result=@{@"backend":@"direct-metal",@"device":device.name,@"compiled":@(compiled),
        @"pixel_cases":@(passed),@"discard_cases":@(discarded),@"max_float_error":@(maxError),@"fast_math":@NO,
        @"depth_cases":@(depthCases),@"max_depth_error":@(maxDepthError),
        @"manifest_sha256":sha256(manifestData),@"runner_sha256":runnerHash};
    NSData *out=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(out.bytes,1,out.length,stdout);printf("\n");return 0;
} }
