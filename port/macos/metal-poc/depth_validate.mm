// Capability and raster-depth observations; this does not emulate Xbox depth.
#define main nativeDrawReplayMain
#include "draw_replay.mm"
#undef main

static float rasterDepth(id<MTLDevice> device, id<MTLCommandQueue> queue,
                         id<MTLRenderPipelineState> pipeline, float z, float bias) {
    MTLTextureDescriptor *descriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatDepth32Float_Stencil8
        width:1 height:1 mipmapped:NO];
    descriptor.usage = MTLTextureUsageRenderTarget; descriptor.storageMode = MTLStorageModePrivate;
    id<MTLTexture> texture = [device newTextureWithDescriptor:descriptor]; require(texture != nil, @"Depth allocation");
    MTLDepthStencilDescriptor *state = [MTLDepthStencilDescriptor new];
    state.depthCompareFunction = MTLCompareFunctionAlways; state.depthWriteEnabled = YES;
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor new];
    pass.depthAttachment.texture = texture; pass.depthAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = MTLStoreActionStore; pass.depthAttachment.clearDepth = 1;
    pass.stencilAttachment.texture = texture; pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.stencilAttachment.storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> command = [queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:pipeline]; [encoder setDepthStencilState:[device newDepthStencilStateWithDescriptor:state]];
    [encoder setCullMode:MTLCullModeNone]; [encoder setDepthBias:bias slopeScale:0 clamp:0];
    [encoder setVertexBytes:&z length:sizeof(z) atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3]; [encoder endEncoding];
    id<MTLBuffer> output = [device newBufferWithLength:256 options:MTLResourceStorageModeShared];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(1,1,1)
                toBuffer:output destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:256
                  options:MTLBlitOptionDepthFromDepthStencil];
    [blit endEncoding]; complete(command);
    float result; memcpy(&result, output.contents, sizeof(result)); require(std::isfinite(result), @"Nonfinite depth"); return result;
}

int main(int argc, const char **argv) { @autoreleasepool {
    require(argc == 2, @"Usage: depth_validate output.json");
    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No Metal device");
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
        "vertex float4 depth_vertex(uint i [[vertex_id]],constant float &z [[buffer(0)]]) {\n"
        "float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};return float4(p[i],z,1);}\n";
    MTLCompileOptions *options = [MTLCompileOptions new]; options.fastMathEnabled = NO; options.preserveInvariance = YES;
    NSError *error = nil; id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    require(library != nil, error.localizedDescription ?: @"Depth shader");
    MTLRenderPipelineDescriptor *description = [MTLRenderPipelineDescriptor new];
    description.vertexFunction = [library newFunctionWithName:@"depth_vertex"];
    description.depthAttachmentPixelFormat = description.stencilAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:description error:&error];
    require(pipeline != nil, error.localizedDescription ?: @"Depth pipeline");
    id<MTLCommandQueue> queue = [device newCommandQueue];
    NSMutableArray *observations = [NSMutableArray new];
    for (float z : {.125f,.25f,.5f,.75f,.875f,.999f}) {
        NSMutableArray *offsets = [NSMutableArray new];
        float unmodified = rasterDepth(device, queue, pipeline, z, 0);
        for (float bias : {-8.f,-1.f,1.f,8.f}) {
            float measured = rasterDepth(device, queue, pipeline, z, bias);
            [offsets addObject:@{@"bias": @(bias), @"depth": @(measured), @"delta": @((double)measured-unmodified)}];
        }
        uint32_t code24 = (uint32_t)std::round((double)z*16777215.0);
        [observations addObject:@{@"source_depth": @(z), @"stored_float_depth": @(unmodified),
            @"ideal_unorm24_nearest_code": @(code24), @"ideal_unorm24_nearest_depth": @(code24/16777215.0),
            @"bias_observations": offsets}];
    }
    NSString *runner = [@(argv[0]).stringByStandardizingPath stringByResolvingSymlinksInPath];
    if (!runner.isAbsolutePath) runner = [NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:runner];
    NSDictionary *result = @{@"schema_version": @1, @"kind": @"native_depth_observation", @"device": device.name,
        @"depth24_unorm_stencil8_supported": @(device.isDepth24Stencil8PixelFormatSupported),
        @"tested_format": @"depth32float_stencil8", @"observations": observations,
        @"ideal_unorm24_step": @(1.0/16777215.0), @"runner": @{@"file": runner, @"sha256": sha256(readFile(runner))},
        @"limits": @[@"Ideal UNORM24 is an arithmetic comparison, not measured original Xbox rounding.",
            @"Native float bias observations are not evidence of NV2A bias behavior.",
            @"No original Xbox depth emulation enabled."]};
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
    require(data && [data writeToFile:@(argv[1]) atomically:YES], @"Could not save observations");
    printf("%s: depth24 supported=%s; %lu depth observations\n", device.name.UTF8String,
           device.isDepth24Stencil8PixelFormatSupported ? "yes" : "no", observations.count);
    return 0;
} }
