/* Isolated GPU test of the shared encoder's target-history and state contract.
 * This owns clears/readbacks; the production encoder performs neither. */
#import "../host/metal_draw_encoder.h"
#include <cstdio>
#include <cstring>
#include <vector>

static void require(bool condition, NSString *message) {
    if (!condition) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
static void complete(id<MTLCommandBuffer> command) {
    [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted, command.error.localizedDescription ?: @"GPU command failed");
}
static id<MTLBuffer> uniforms(id<MTLDevice> device, NSUInteger size, const float first[4]) {
    std::vector<uint8_t> bytes(size + 16); memcpy(bytes.data() + 16, first, 16);
    return [device newBufferWithBytes:bytes.data() length:bytes.size() options:MTLResourceStorageModeShared];
}
static std::vector<uint8_t> readPlane(id<MTLDevice> device, id<MTLCommandQueue> queue,
        id<MTLTexture> texture, bool depth) {
    NSUInteger row = 256, bpp = depth ? 4 : 1;
    id<MTLBuffer> buffer = [device newBufferWithLength:row * texture.height options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> command = [queue commandBuffer]; id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
        sourceSize:MTLSizeMake(texture.width, texture.height, 1) toBuffer:buffer destinationOffset:0
        destinationBytesPerRow:row destinationBytesPerImage:row * texture.height
        options:depth ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionStencilFromDepthStencil];
    [blit endEncoding]; complete(command);
    std::vector<uint8_t> result(texture.width * texture.height * bpp);
    for (NSUInteger y = 0; y < texture.height; y++)
        memcpy(result.data() + y * texture.width * bpp, (uint8_t *)buffer.contents + y * row, texture.width * bpp);
    return result;
}
int main() { @autoreleasepool {
    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No Metal device");
    id<MTLCommandQueue> queue = [device newCommandQueue];
    NSString *source = @R"MSL(
#include <metal_stdlib>
using namespace metal;
struct Inputs { float4 position [[attribute(0)]]; };
struct VS { float4 c[195]; };
struct PS { float4 c[38]; };
struct Output { float4 position [[position]]; float pointSize [[point_size]]; };
vertex Output testVertex(Inputs v [[stage_in]], constant VS &u [[buffer(0)]]) {
    return {v.position + u.c[0], 1.0f};
}
fragment float4 testFragment(constant PS &u [[buffer(0)]]) { return u.c[0]; }
fragment float4 sampledFragment(constant PS &u [[buffer(0)]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
    return t.sample(s, float2(0.5f)) * u.c[0];
}
)MSL";
    NSError *error = nil; MTLCompileOptions *options = [MTLCompileOptions new];
    if (@available(macOS 15.0, *)) options.mathMode = MTLMathModeSafe;
    else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        options.fastMathEnabled = NO;
#pragma clang diagnostic pop
    }
    id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    require(library != nil, error.localizedDescription ?: @"Test shader compilation failed");
    MTLTextureDescriptor *description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
        width:16 height:16 mipmapped:NO];
    description.storageMode = MTLStorageModeShared; description.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    id<MTLTexture> color = [device newTextureWithDescriptor:description];
    description.pixelFormat = MTLPixelFormatDepth32Float_Stencil8; description.storageMode = MTLStorageModePrivate;
    description.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> depth = [device newTextureWithDescriptor:description]; require(color && depth, @"Test attachments failed");
    std::vector<uint8_t> initial(16 * 16 * 4);
    for (size_t i = 0; i < 256; i++) { initial[i * 4] = 10; initial[i * 4 + 1] = 20; initial[i * 4 + 2] = 30; initial[i * 4 + 3] = 255; }
    [color replaceRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0 withBytes:initial.data() bytesPerRow:64];
    id<MTLCommandBuffer> clear = [queue commandBuffer]; MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.depthAttachment.texture = pass.stencilAttachment.texture = depth;
    pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.clearDepth = 1; pass.stencilAttachment.clearStencil = 3;
    [[clear renderCommandEncoderWithDescriptor:pass] endEncoding]; complete(clear);
    std::vector<uint8_t> vertices(3 * HaloMetalVertexStride + 16);
    const float positions[3][4] = {{-1, -1, 0, 1}, {3, -1, 0, 1}, {-1, 3, 0, 1}};
    for (unsigned i = 0; i < 3; i++) memcpy(vertices.data() + 16 + i * HaloMetalVertexStride, positions[i], 16);
    const uint32_t indices[7] = {0, 0, 0, 0, 0, 1, 2};
    HaloMetalDraw draw;
    draw.vertexFunction = [library newFunctionWithName:@"testVertex"];
    draw.fragmentFunction = [library newFunctionWithName:@"testFragment"];
    draw.color = color; draw.depthStencil = depth;
    draw.vertices = [device newBufferWithBytes:vertices.data() length:vertices.size() options:MTLResourceStorageModeShared];
    draw.indices = [device newBufferWithBytes:indices length:sizeof(indices) options:MTLResourceStorageModeShared];
    draw.vertexOffset = draw.indexOffset = draw.vertexUniformOffset = draw.pixelUniformOffset = 16;
    draw.vertexCount = draw.indexCount = 3;
    const float firstZ[4] = {0, 0, .25f, 0}, red[4] = {1, 0, 0, 1};
    draw.vertexUniforms = uniforms(device, HaloMetalVertexUniformSize, firstZ);
    draw.pixelUniforms = uniforms(device, HaloMetalPixelUniformSize, red);
    auto &s = draw.state;
    s.color_write_mask = 1; s.blend_source = 2; s.blend_destination = 1; s.blend_operation = 1;
    s.depth_enabled = s.depth_write = 1; s.depth_compare = 2;
    s.stencil_enabled = 1; s.stencil_compare = 8; s.stencil_read_mask = s.stencil_write_mask = 255;
    s.stencil_fail = s.stencil_depth_fail = 1; s.stencil_pass = 3; s.stencil_reference = 7;
    s.viewport[2] = s.viewport[3] = 16; s.viewport[5] = 1;
    s.scissor[0] = s.scissor[1] = 4; s.scissor[2] = s.scissor[3] = 8;
    HaloMetalDrawEncoder *encoder = [[HaloMetalDrawEncoder alloc] initWithDevice:device];
    require([encoder prepareDraw:draw error:&error], error.localizedDescription ?: @"First draw preparation failed");
    HaloMetalDraw farther = draw;
    const float fartherZ[4] = {0, 0, .75f, 0}, green[4] = {0, 1, 0, 1};
    farther.vertexUniforms = uniforms(device, HaloMetalVertexUniformSize, fartherZ);
    farther.pixelUniforms = uniforms(device, HaloMetalPixelUniformSize, green);
    id<MTLCommandBuffer> command = [queue commandBuffer];
    require([encoder encodeDraw:draw commandBuffer:command error:&error], error.localizedDescription ?: @"First draw encoding failed");
    require([encoder encodeDraw:farther commandBuffer:command error:&error], error.localizedDescription ?: @"Second draw encoding failed");
    complete(command);
    std::vector<uint8_t> rgba(16 * 16 * 4); [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0];
    auto depthBytes = readPlane(device, queue, depth, true), stencilBytes = readPlane(device, queue, depth, false);
    for (unsigned y = 0; y < 16; y++) for (unsigned x = 0; x < 16; x++) {
        bool inside = x >= 4 && x < 12 && y >= 4 && y < 12; size_t i = y * 16 + x;
        require(rgba[i * 4] == (inside ? 255 : 10) && rgba[i * 4 + 1] == 20 && rgba[i * 4 + 2] == 30 && rgba[i * 4 + 3] == 255,
            @"LOAD/STORE, color mask, depth comparison or scissor changed original color history");
        float z; memcpy(&z, depthBytes.data() + i * 4, 4);
        require(z == (inside ? .25f : 1.0f) && stencilBytes[i] == (inside ? 7 : 3),
            @"LOAD/STORE did not preserve original depth/stencil history");
    }
    HaloMetalDraw blended = farther;
    blended.state.color_write_mask = 15; blended.state.blend_enabled = 1;
    blended.state.blend_source = 12; blended.state.blend_destination = 13;
    blended.state.blend_color[0] = blended.state.blend_color[3] = 1;
    blended.state.depth_enabled = blended.state.depth_write = 0;
    blended.state.stencil_compare = 3; blended.state.stencil_write_mask = 0; blended.state.stencil_pass = 1;
    command = [queue commandBuffer];
    require([encoder encodeDraw:blended commandBuffer:command error:&error], error.localizedDescription ?: @"Blend draw encoding failed"); complete(command);
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0];
    for (unsigned y = 0; y < 16; y++) for (unsigned x = 0; x < 16; x++) {
        bool inside = x >= 4 && x < 12 && y >= 4 && y < 12; size_t i = y * 16 + x;
        require(rgba[i * 4] == (inside ? 0 : 10) && rgba[i * 4 + 1] == 20 && rgba[i * 4 + 2] == 30 && rgba[i * 4 + 3] == 255,
            @"Explicit constant blend/stencil comparison state did not preserve expected channels");
    }
    // Query geometry is depth/stencil tested against the existing attachments,
    // but has no color, depth or stencil writes. Each encoder has a fresh word;
    // the unrelated canary at offset 0 detects an unintended Disabled setter.
    const auto beforeQueryColor = rgba;
    const auto beforeQueryDepth = readPlane(device, queue, depth, true);
    const auto beforeQueryStencil = readPlane(device, queue, depth, false);
    const uint64_t canary = UINT64_C(0xa5c37e1902468bdf);
    const uint64_t initialWords[5] = {canary, 0, 0, 0, canary};
    id<MTLBuffer> visibility = [device newBufferWithBytes:initialWords length:sizeof(initialWords)
        options:MTLResourceStorageModeShared];
    require(visibility != nil, @"Visibility buffer allocation failed");
    HaloMetalDraw query = draw;
    query.state.color_write_mask = 0; query.state.depth_write = 0; query.state.depth_compare = 4;
    query.state.stencil_compare = 3; query.state.stencil_write_mask = 0;
    query.state.stencil_fail = query.state.stencil_depth_fail = query.state.stencil_pass = 1;
    query.visibilityBuffer = visibility; query.visibilityOffset = 8;
    query.visibilityMode = MTLVisibilityResultModeCounting;
    HaloMetalDraw occludedQuery = query;
    occludedQuery.vertexUniforms = farther.vertexUniforms; occludedQuery.visibilityOffset = 16;
    HaloMetalDraw booleanQuery = query;
    booleanQuery.visibilityMode = MTLVisibilityResultModeBoolean; booleanQuery.visibilityOffset = 24;
    command = [queue commandBuffer];
    require([encoder encodeDraw:query commandBuffer:command error:&error], error.localizedDescription ?: @"Counting query encoding failed");
    require([encoder encodeDraw:occludedQuery commandBuffer:command error:&error], error.localizedDescription ?: @"Occluded query encoding failed");
    require([encoder encodeDraw:booleanQuery commandBuffer:command error:&error], error.localizedDescription ?: @"Boolean query encoding failed");
    // A draw outside a query must leave all previous result words alone.
    HaloMetalDraw noQuery = query;
    noQuery.visibilityBuffer = nil; noQuery.visibilityOffset = 0; noQuery.visibilityMode = MTLVisibilityResultModeDisabled;
    require([encoder encodeDraw:noQuery commandBuffer:command error:&error], error.localizedDescription ?: @"Inactive-query draw encoding failed");
    complete(command);
    const uint64_t *words = (const uint64_t *)visibility.contents;
    require(words[0] == canary && words[4] == canary, @"A query encoder reset an unrelated result word");
    require(words[1] == 64 && words[2] == 0 && words[3] == 1,
        @"Fresh Counting/Boolean words did not preserve visible/occluded query results across encoders");
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0];
    require(rgba == beforeQueryColor && readPlane(device, queue, depth, true) == beforeQueryDepth &&
        readPlane(device, queue, depth, false) == beforeQueryStencil,
        @"Readonly visibility queries changed original color, depth or stencil attachments");
    HaloMetalDraw invalidQuery = query; invalidQuery.visibilityBuffer = nil;
    require(![encoder prepareDraw:invalidQuery error:&error] && error.code == HaloMetalDrawInvalid, @"Active query without a result buffer accepted");
    invalidQuery = noQuery; invalidQuery.visibilityOffset = 8;
    require(![encoder prepareDraw:invalidQuery error:&error], @"Inactive query with an offset accepted");
    invalidQuery = query; invalidQuery.visibilityMode = MTLVisibilityResultModeDisabled;
    require(![encoder prepareDraw:invalidQuery error:&error], @"Inactive query with a result buffer accepted");
    invalidQuery = query; invalidQuery.visibilityMode = (MTLVisibilityResultMode)3;
    require(![encoder prepareDraw:invalidQuery error:&error], @"Unknown visibility mode accepted");
    invalidQuery = query; invalidQuery.visibilityOffset = 4;
    require(![encoder prepareDraw:invalidQuery error:&error], @"Unaligned result word accepted");
    invalidQuery = query; invalidQuery.visibilityBuffer = [device newBufferWithLength:12 options:MTLResourceStorageModeShared];
    require(![encoder prepareDraw:invalidQuery error:&error], @"Truncated result word accepted");
    invalidQuery = query; invalidQuery.visibilityOffset = sizeof(initialWords);
    require(![encoder prepareDraw:invalidQuery error:&error], @"Out-of-range result word accepted");
    invalidQuery = query; invalidQuery.visibilityOffset = NSUIntegerMax - 7;
    require(![encoder prepareDraw:invalidQuery error:&error], @"Overflowing result offset accepted");
    invalidQuery = query; invalidQuery.visibilityBuffer = [device newBufferWithLength:sizeof(initialWords) options:MTLResourceStorageModePrivate];
    require(![encoder prepareDraw:invalidQuery error:&error], @"Non-shared result buffer accepted");
    HaloMetalDraw invalid = draw; invalid.state.depth_compare = 0;
    require(![encoder prepareDraw:invalid error:&error] && error.code == HaloMetalDrawInvalid, @"Unknown comparison accepted");
    invalid = draw; invalid.pixelUniformOffset = 32;
    require(![encoder prepareDraw:invalid error:&error], @"Truncated uniform range accepted");
    invalid = draw; const uint32_t badIndices[3] = {0, 1, 3};
    invalid.indices = [device newBufferWithBytes:badIndices length:sizeof(badIndices) options:MTLResourceStorageModeShared]; invalid.indexOffset = 0;
    require(![encoder prepareDraw:invalid error:&error], @"Out-of-range expanded index accepted");
    invalid = draw; invalid.fragmentFunction = [library newFunctionWithName:@"sampledFragment"];
    require(![encoder prepareDraw:invalid error:&error], @"Missing used texture accepted");
    MTLSamplerDescriptor *sampler = [MTLSamplerDescriptor new]; invalid.samplers[0] = [device newSamplerStateWithDescriptor:sampler];
    invalid.textures[0] = color;
    require(![encoder prepareDraw:invalid error:&error], @"Read/write target alias accepted");
    description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:2 height:2 mipmapped:NO];
    description.usage = MTLTextureUsageShaderRead; invalid.textures[0] = [device newTextureWithDescriptor:description];
    require([encoder prepareDraw:invalid error:&error], error.localizedDescription ?: @"Valid reflected sampler/texture rejected");
    require(![encoder encodeDraw:draw commandBuffer:command error:&error], @"Submitted command buffer accepted");
    [encoder removePipelinesForVertexFunction:draw.vertexFunction fragmentFunction:nil];
    require([encoder prepareDraw:draw error:&error], error.localizedDescription ?: @"Cache eviction lost valid original program");
    [encoder clearCaches];
    printf("{\"complete\":true,\"color_depth_stencil_history\":true,\"state_and_resource_validation\":true,"
        "\"visibility_readonly_count\":64,\"visibility_occluded_count\":0,\"visibility_boolean\":1,"
        "\"visibility_offset_validation\":true,\"cpu_query_timing_verified\":false}\n");
    return 0;
} }
