// Numerical and raster-space validation of emitted Xbox vertex arithmetic.
// The compute entry adaptation is test-only; render cases use the native
// vertex shader exactly as returned by nv2a_vertex_shader_to_msl.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <cmath>
#include <cstdio>
#include <cstring>

struct VertexUniforms {
    simd_float4 c[192], viewport_scale, viewport_offset;
    float point_size, screen_offset, padding[2];
};
static_assert(sizeof(VertexUniforms)==3120,"Metal vertex uniform ABI");

static void require(bool ok, NSString *reason) {
    if (!ok) { fprintf(stderr,"metal-vertex: %s\n",reason.UTF8String); exit(1); }
}
static NSData *read(NSString *path) {
    NSError *error=nil;
    NSData *data=[NSData dataWithContentsOfFile:path options:0 error:&error];
    require(data!=nil,error.localizedDescription ?: path);return data;
}
static simd_float4 vector(NSArray *values) {
    require(values.count==4,@"Expected a four-component fixture vector");
    return {[values[0] floatValue],[values[1] floatValue],[values[2] floatValue],[values[3] floatValue]};
}
static VertexUniforms uniforms(NSDictionary *fixture) {
    VertexUniforms result={};NSDictionary *u=fixture[@"uniforms"];
    require([u[@"c"] count]==192,@"Expected 192 vertex constants");
    for(int index=0;index<192;index++)result.c[index]=vector(u[@"c"][index]);
    result.viewport_scale=vector(u[@"viewport_scale"]);result.viewport_offset=vector(u[@"viewport_offset"]);
    result.point_size=[u[@"point_size"] floatValue];result.screen_offset=[u[@"screen_offset"] floatValue];
    return result;
}
static void attributes(NSDictionary *fixture,simd_float4 *values) {
    require([fixture[@"attributes"] count]==16,@"Expected 16 attributes");
    for(int index=0;index<16;index++)values[index]=vector(fixture[@"attributes"][index]);
    for(NSString *key in fixture[@"packed_attributes"]) {
        unsigned index=key.intValue;require(index<16,@"Invalid packed attribute index");
        uint32_t bits=[fixture[@"packed_attributes"][key] unsignedIntValue];
        memcpy(&values[index],&bits,sizeof(bits));
    }
}
static id<MTLLibrary> library(id<MTLDevice> device,NSString *source,NSString *label) {
    NSError *error=nil;MTLCompileOptions *options=[MTLCompileOptions new];
    options.fastMathEnabled=NO;options.preserveInvariance=YES;
    id<MTLLibrary> result=[device newLibraryWithSource:source options:options error:&error];
    require(result!=nil,[NSString stringWithFormat:@"%@: %@",label,error.localizedDescription]);return result;
}
static NSString *shaderSource(NSString *root,NSDictionary *fixture) {
    return [[NSString alloc] initWithData:read([root stringByAppendingPathComponent:fixture[@"shader"]])
                                encoding:NSUTF8StringEncoding];
}
static void complete(id<MTLCommandBuffer> command) {
    [command commit];[command waitUntilCompleted];
    require(command.status==MTLCommandBufferStatusCompleted,command.error.localizedDescription ?: @"GPU command failed");
}

int main(int argc,const char **argv) { @autoreleasepool {
    require(argc==2,@"Usage: vertex_validate manifest.json");
    NSString *path=[NSString stringWithUTF8String:argv[1]],*root=path.stringByDeletingLastPathComponent;
    NSError *error=nil;
    NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:read(path) options:0 error:&error];
    require([manifest isKindOfClass:NSDictionary.class],error.localizedDescription ?: @"Invalid manifest");
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();require(device!=nil,@"No Metal device");
    id<MTLCommandQueue> queue=[device newCommandQueue];require(queue!=nil,@"No Metal command queue");
    NSUInteger numerical=0,rendered=0,components=0;double maxAbsolute=0,maxRelative=0;
    for(NSDictionary *fixture in manifest[@"numerical"]) {
        id<MTLLibrary> lib=library(device,shaderSource(root,fixture),fixture[@"name"]);
        id<MTLFunction> function=[lib newFunctionWithName:@"validate_vertex"];
        id<MTLComputePipelineState> pipeline=[device newComputePipelineStateWithFunction:function error:&error];
        require(pipeline!=nil,error.localizedDescription);
        simd_float4 input[16];attributes(fixture,input);VertexUniforms u=uniforms(fixture);
        id<MTLBuffer> output=[device newBufferWithLength:10*sizeof(simd_float4) options:MTLResourceStorageModeShared];
        require(output!=nil,@"No compute output buffer");
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];[encoder setBytes:input length:sizeof(input) atIndex:0];
        [encoder setBytes:&u length:sizeof(u) atIndex:1];[encoder setBuffer:output offset:0 atIndex:2];
        [encoder dispatchThreads:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(1,1,1)];
        [encoder endEncoding];complete(command);
        const float *actual=(const float *)output.contents;
        for(NSString *key in fixture[@"expected"]) {
            unsigned index=key.intValue;require(index<10,@"Invalid expected output index");
            NSArray *expected=fixture[@"expected"][key];require(expected.count==4,@"Invalid expected vector");
            for(unsigned component=0;component<4;component++) {
                float value=actual[index*4+component],reference=[expected[component] floatValue];
                double absolute=fabs((double)value-reference),relative=absolute/(1+fabs((double)reference));
                maxAbsolute=fmax(maxAbsolute,absolute);maxRelative=fmax(maxRelative,relative);
                require(std::isfinite(value) && relative<0.00002,
                    [NSString stringWithFormat:@"%@: output %u channel %u actual %.9g expected %.9g",
                     fixture[@"name"],index,component,value,reference]);components++;
            }
        }
        numerical++;
    }
    MTLTextureDescriptor *textureDescription=[MTLTextureDescriptor
        texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA32Float width:8 height:8 mipmapped:NO];
    textureDescription.storageMode=MTLStorageModeShared;textureDescription.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> texture=[device newTextureWithDescriptor:textureDescription];require(texture!=nil,@"No render target");
    for(NSDictionary *fixture in manifest[@"render"]) {
        NSString *source=[shaderSource(root,fixture) stringByAppendingString:
            @"\nfragment float4 validate_fragment(float4 screen [[position]]) { return float4(screen.xyz,1.0); }\n"];
        id<MTLLibrary> lib=library(device,source,fixture[@"name"]);
        MTLRenderPipelineDescriptor *description=[MTLRenderPipelineDescriptor new];
        description.vertexFunction=[lib newFunctionWithName:@"xgpu_vertex"];
        description.fragmentFunction=[lib newFunctionWithName:@"validate_fragment"];
        description.colorAttachments[0].pixelFormat=MTLPixelFormatRGBA32Float;
        description.inputPrimitiveTopology=MTLPrimitiveTopologyClassPoint;
        MTLVertexDescriptor *layout=[MTLVertexDescriptor vertexDescriptor];
        for(int index=0;index<16;index++) {
            layout.attributes[index].format=MTLVertexFormatFloat4;
            layout.attributes[index].offset=index*sizeof(simd_float4);layout.attributes[index].bufferIndex=1;
        }
        layout.layouts[1].stride=16*sizeof(simd_float4);description.vertexDescriptor=layout;
        id<MTLRenderPipelineState> pipeline=[device newRenderPipelineStateWithDescriptor:description error:&error];
        require(pipeline!=nil,error.localizedDescription);
        simd_float4 input[16];attributes(fixture,input);VertexUniforms u=uniforms(fixture);
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=texture;pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        pass.colorAttachments[0].clearColor=MTLClearColorMake(-1,-1,-1,-1);
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLRenderCommandEncoder> encoder=[command renderCommandEncoderWithDescriptor:pass];
        MTLViewport viewport={0,0,8,8,0,1};[encoder setViewport:viewport];
        [encoder setRenderPipelineState:pipeline];[encoder setVertexBytes:&u length:sizeof(u) atIndex:0];
        [encoder setVertexBytes:input length:sizeof(input) atIndex:1];
        [encoder drawPrimitives:MTLPrimitiveTypePoint vertexStart:0 vertexCount:1];
        [encoder endEncoding];complete(command);
        float pixels[8*8*4];[texture getBytes:pixels bytesPerRow:8*4*sizeof(float)
                                fromRegion:MTLRegionMake2D(0,0,8,8) mipmapLevel:0];
        unsigned column=[fixture[@"pixel"][0] unsignedIntValue],row=[fixture[@"pixel"][1] unsignedIntValue];
        for(unsigned y=0;y<8;y++)for(unsigned x=0;x<8;x++)for(unsigned component=0;component<4;component++) {
            float expected=(x==column && y==row)?[fixture[@"expected"][component] floatValue]:-1;
            float value=pixels[(y*8+x)*4+component];double absolute=fabs((double)value-expected);
            require(std::isfinite(value) && absolute<0.00002,
                [NSString stringWithFormat:@"%@: pixel (%u,%u) channel %u actual %.9g expected %.9g",
                 fixture[@"name"],x,y,component,value,expected]);
            maxAbsolute=fmax(maxAbsolute,absolute);maxRelative=fmax(maxRelative,absolute/(1+fabs(expected)));components++;
        }
        rendered++;
    }
    NSDictionary *result=@{@"backend":@"direct-metal",@"device":device.name,
        @"numerical_cases":@(numerical),@"render_cases":@(rendered),@"compared_components":@(components),
        @"max_absolute_error":@(maxAbsolute),@"max_relative_error":@(maxRelative),
        @"nonfinite_values":@0,@"fast_math":@NO,@"position_invariance":@YES};
    NSData *data=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(data.bytes,1,data.length,stdout);printf("\n");return 0;
} }
