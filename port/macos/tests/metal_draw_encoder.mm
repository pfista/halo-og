/* Isolated GPU test of the shared encoder's target-history and state contract.
 * This owns clears/readbacks; the production encoder performs neither. */
#import "../host/metal_draw_encoder.h"
#include "../include/halo_metal_vertex_input.h"
#include <limits>
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
static BOOL encode(HaloMetalDrawEncoder *encoder, const HaloMetalDraw &draw,
                   id<MTLCommandBuffer> command, bool reuse, NSError **error) {
    return reuse ? [encoder encodeDraw:draw commandBuffer:command reusePass:YES error:error] :
                   [encoder encodeDraw:draw commandBuffer:command error:error];
}
static void append(std::vector<uint8_t> &result, const std::vector<uint8_t> &bytes) {
    result.insert(result.end(),bytes.begin(),bytes.end());
}
int main(int argc, const char **argv) { @autoreleasepool {
    const bool cached = argc > 1 && !strcmp(argv[1],"cached");
    const bool reuse = cached || (argc > 1 && !strcmp(argv[1],"reuse"));
    require(argc <= 3 && (argc < 2 || reuse || !strcmp(argv[1],"isolated")), @"Invalid test mode");
    std::vector<uint8_t> checkpoints;
    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No Metal device");
    id<MTLCommandQueue> queue = [device newCommandQueue];
    NSString *source = @R"MSL(
#include <metal_stdlib>
using namespace metal;
struct Inputs { float4 position [[attribute(0)]]; };
struct VS { float4 c[195]; };
struct PS { float4 c[38]; };
struct OversizedPS { float4 c[39]; };
struct Output { float4 position [[position]]; float pointSize [[point_size]]; };
vertex Output testVertex(Inputs v [[stage_in]], constant VS &u [[buffer(0)]]) {
    return {v.position + u.c[0], 1.0f};
}
struct CompactElement { uint reg, type, offset, stride; };
struct CompactInput { uint version, elementCount, vertexCount, packedMask; CompactElement elements[16]; float4 fixed[16]; };
vertex Output compactVertex(uint id [[vertex_id]], device const uchar *bytes [[buffer(1)]], constant VS &u [[buffer(0)]]) {
    device const CompactInput &input = *(device const CompactInput *)bytes;
    device const float4 &position = *(device const float4 *)(bytes + input.elements[0].offset + id * input.elements[0].stride);
    return {position + u.c[0], 1.0f};
}
fragment float4 testFragment(constant PS &u [[buffer(0)]]) { return u.c[0]; }
fragment float4 sampledFragment(constant PS &u [[buffer(0)]], texture2d<float> t [[texture(0)]], sampler s [[sampler(0)]]) {
    return t.sample(s, float2(0.5f)) * u.c[0];
}
fragment float4 sampledEdgesFragment(texture2d<float> first [[texture(0)]], sampler firstSampler [[sampler(0)]],
        texture2d<float> last [[texture(3)]], sampler lastSampler [[sampler(3)]]) {
    return first.sample(firstSampler, float2(0.5f)) + last.sample(lastSampler, float2(0.5f));
}
fragment float4 unsupportedBufferFragment(constant PS &u [[buffer(1)]]) { return u.c[0]; }
fragment float4 oversizedBufferFragment(constant OversizedPS &u [[buffer(0)]]) { return u.c[38]; }
fragment float4 unsupportedTextureFragment(texture2d<float> t [[texture(4)]], sampler s [[sampler(0)]]) {
    return t.sample(s, float2(0.5f));
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
    require(!encoder.cacheBindingsEnabled && !encoder.bindingSetCount && !encoder.bindingSkipCount,
            @"Binding cache or counters did not default to off and zero");
    encoder.cacheBindingsEnabled = cached;
    require(!encoder.diagnosticsEnabled && encoder.pipelineCreationCount == 0 && encoder.pipelineCreationNanoseconds == 0,
            @"Pipeline diagnostics did not default to disabled and zero");
    require([encoder prepareDraw:draw error:&error], error.localizedDescription ?: @"First draw preparation failed");
    require(encoder.pipelineCreationCount == 0 && encoder.pipelineCreationNanoseconds == 0,
            @"Disabled pipeline diagnostics accumulated creation work");
    encoder.diagnosticsEnabled = YES;
    require([encoder prepareDraw:draw error:&error] && encoder.pipelineCreationCount == 0 && encoder.pipelineCreationNanoseconds == 0,
            @"Warm pipeline performed diagnostic creation work");
    [encoder clearCaches];
    require([encoder prepareDraw:draw error:&error] && encoder.pipelineCreationCount == 1 && encoder.pipelineCreationNanoseconds > 0,
            @"Enabled pipeline miss did not record its synchronous creation");
    const uint64_t firstPipelineNanoseconds = encoder.pipelineCreationNanoseconds;
    require([encoder prepareDraw:draw error:&error] && encoder.pipelineCreationCount == 1 &&
            encoder.pipelineCreationNanoseconds == firstPipelineNanoseconds, @"Pipeline cache hit changed cumulative timing");
    encoder.diagnosticsEnabled = NO; [encoder clearCaches];
    require([encoder prepareDraw:draw error:&error] && encoder.pipelineCreationCount == 1 &&
            encoder.pipelineCreationNanoseconds == firstPipelineNanoseconds, @"Disabling or clearing reset cumulative timing");
    encoder.diagnosticsEnabled = YES;
    uint32_t usedTextures = UINT32_MAX;
    require([encoder usedTextureMaskForDraw:draw mask:&usedTextures error:&error] && usedTextures == 0,
            @"Untextured draw returned used textures");
    HaloMetalDraw farther = draw;
    const float fartherZ[4] = {0, 0, .75f, 0}, green[4] = {0, 1, 0, 1};
    farther.vertexUniforms = uniforms(device, HaloMetalVertexUniformSize, fartherZ);
    farther.pixelUniforms = uniforms(device, HaloMetalPixelUniformSize, green);
    id<MTLCommandBuffer> command = [queue commandBuffer];
    require(encode(encoder,draw,command,reuse,&error), error.localizedDescription ?: @"First draw encoding failed");
    const NSUInteger firstSets = encoder.bindingSetCount;
    require(encode(encoder,farther,command,reuse,&error), error.localizedDescription ?: @"Second draw encoding failed");
    require(encoder.bindingSetCount > firstSets && (cached ? encoder.bindingSkipCount > 0 : encoder.bindingSkipCount == 0),
            @"Changing uniforms were skipped or equal bindings did not use the selected cache mode");
    [encoder endEncoding];
    require(encoder.renderPassCount == (reuse ? 1u : 2u), @"Consecutive compatible draws did not use the expected number of passes");
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
    append(checkpoints,rgba); append(checkpoints,depthBytes); append(checkpoints,stencilBytes);
    HaloMetalDraw blended = farther;
    blended.state.color_write_mask = 15; blended.state.blend_enabled = 1;
    blended.state.blend_source = 12; blended.state.blend_destination = 13;
    blended.state.blend_color[0] = blended.state.blend_color[3] = 1;
    blended.state.depth_enabled = blended.state.depth_write = 0;
    blended.state.stencil_compare = 3; blended.state.stencil_write_mask = 0; blended.state.stencil_pass = 1;
    command = [queue commandBuffer];
    require(encode(encoder,blended,command,reuse,&error), error.localizedDescription ?: @"Blend draw encoding failed"); [encoder endEncoding]; complete(command);
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0];
    for (unsigned y = 0; y < 16; y++) for (unsigned x = 0; x < 16; x++) {
        bool inside = x >= 4 && x < 12 && y >= 4 && y < 12; size_t i = y * 16 + x;
        require(rgba[i * 4] == (inside ? 0 : 10) && rgba[i * 4 + 1] == 20 && rgba[i * 4 + 2] == 30 && rgba[i * 4 + 3] == 255,
            @"Explicit constant blend/stencil comparison state did not preserve expected channels");
    }
    append(checkpoints,rgba); append(checkpoints,readPlane(device,queue,depth,true));
    append(checkpoints,readPlane(device,queue,depth,false));
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
    HaloMetalDraw noQuery = query;
    noQuery.visibilityBuffer = nil; noQuery.visibilityOffset = 0; noQuery.visibilityMode = MTLVisibilityResultModeDisabled;
    command = [queue commandBuffer];
    const NSUInteger queryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), error.localizedDescription ?: @"Ordinary draw before query failed");
    require(encode(encoder,query,command,reuse,&error), error.localizedDescription ?: @"Counting query encoding failed");
    require(encode(encoder,occludedQuery,command,reuse,&error), error.localizedDescription ?: @"Occluded query encoding failed");
    require(encode(encoder,booleanQuery,command,reuse,&error), error.localizedDescription ?: @"Boolean query encoding failed");
    // A draw outside a query must leave all previous result words alone.
    require(encode(encoder,noQuery,command,reuse,&error), error.localizedDescription ?: @"Inactive-query draw encoding failed");
    require(encode(encoder,noQuery,command,reuse,&error), error.localizedDescription ?: @"Consecutive inactive-query draw encoding failed");
    [encoder endEncoding];
    require(encoder.renderPassCount - queryPasses == (reuse ? 5u : 6u), @"Query draws did not retain isolated passes between ordinary draw runs");
    complete(command);
    const uint64_t *words = (const uint64_t *)visibility.contents;
    require(words[0] == canary && words[4] == canary, @"A query encoder reset an unrelated result word");
    require(words[1] == 64 && words[2] == 0 && words[3] == 1,
        @"Fresh Counting/Boolean words did not preserve visible/occluded query results across encoders");
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0, 0, 16, 16) mipmapLevel:0];
    require(rgba == beforeQueryColor && readPlane(device, queue, depth, true) == beforeQueryDepth &&
        readPlane(device, queue, depth, false) == beforeQueryStencil,
        @"Readonly visibility queries changed original color, depth or stencil attachments");
    append(checkpoints,rgba); append(checkpoints,readPlane(device,queue,depth,true));
    append(checkpoints,readPlane(device,queue,depth,false));
    const uint8_t *queryBytes = (const uint8_t *)visibility.contents;
    checkpoints.insert(checkpoints.end(),queryBytes,queryBytes + sizeof(initialWords));

    // Exact attachment identity forms a boundary, including returning to an
    // earlier target. No-op draws make all history checks independent of raster
    // coverage and ensure the repeated middle target alone can share a pass.
    description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:16 height:16 mipmapped:NO];
    description.storageMode = MTLStorageModeShared;
    description.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    id<MTLTexture> alternate = [device newTextureWithDescriptor:description];
    require(alternate != nil, @"Alternate attachment allocation failed");
    [alternate replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:initial.data() bytesPerRow:64];
    HaloMetalDraw alternateDraw = noQuery; alternateDraw.color = alternate;
    command = [queue commandBuffer];
    NSUInteger boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), @"First attachment draw failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Attachment switch draw failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Repeated alternate attachment draw failed");
    require(encode(encoder,noQuery,command,reuse,&error), @"Returning attachment draw failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == (reuse ? 3u : 4u), @"Attachment switches were not pass boundaries");
    std::vector<uint8_t> alternateBytes(initial.size());
    [alternate getBytes:alternateBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    require(alternateBytes == initial, @"Attachment switch changed the alternate target");

    // Depth/stencil identity is independent of color identity. Keep the color
    // fixed while moving to another initialized depth/stencil object and back.
    description.pixelFormat = MTLPixelFormatDepth32Float_Stencil8;
    description.storageMode = MTLStorageModePrivate; description.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> alternateDepth = [device newTextureWithDescriptor:description];
    require(alternateDepth != nil, @"Alternate depth/stencil allocation failed");
    clear = [queue commandBuffer]; pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.depthAttachment.texture = pass.stencilAttachment.texture = alternateDepth;
    pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.clearDepth = 1; pass.stencilAttachment.clearStencil = 3;
    [[clear renderCommandEncoderWithDescriptor:pass] endEncoding]; complete(clear);
    HaloMetalDraw alternateDepthDraw = noQuery; alternateDepthDraw.depthStencil = alternateDepth;
    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), @"Draw before depth attachment switch failed");
    require(encode(encoder,alternateDepthDraw,command,reuse,&error), @"Depth attachment switch draw failed");
    require(encode(encoder,alternateDepthDraw,command,reuse,&error), @"Repeated depth attachment draw failed");
    require(encode(encoder,noQuery,command,reuse,&error), @"Returning depth attachment draw failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == (reuse ? 3u : 4u), @"Depth attachment switches were not pass boundaries");
    const auto alternateDepthBytes = readPlane(device,queue,alternateDepth,true);
    const auto alternateStencilBytes = readPlane(device,queue,alternateDepth,false);
    for (size_t i = 0; i < 256; i++) {
        float z; memcpy(&z,alternateDepthBytes.data() + i*4,4);
        require(z == 1 && alternateStencilBytes[i] == 3, @"Depth attachment switch changed readonly target history");
    }
    append(checkpoints,alternateDepthBytes); append(checkpoints,alternateStencilBytes);

    // A different command buffer cannot inherit a retained encoder, even when
    // all attachments match. Both buffers must be independently submittable.
    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), @"Draw on first command buffer failed");
    id<MTLCommandBuffer> nextCommand = [queue commandBuffer];
    require(encode(encoder,noQuery,nextCommand,reuse,&error), @"Draw on next command buffer failed");
    complete(command); [encoder endEncoding]; complete(nextCommand);
    require(encoder.renderPassCount - boundaryPasses == 2, @"Command buffer switch was not a pass boundary");

    // Explicit boundaries permit intervening copy and clear encoders. Draws
    // following a boundary must reload the resulting attachment history.
    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), @"Draw before copy failed");
    [encoder endEncoding];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    require(blit != nil, @"Copy encoder after draw boundary failed");
    [blit copyFromTexture:color sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
        sourceSize:MTLSizeMake(16,16,1) toTexture:alternate destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];
    [blit endEncoding];
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Draw after copy failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Repeated draw after copy failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == (reuse ? 2u : 3u), @"Copy boundary did not restart draw pass reuse");
    [alternate getBytes:alternateBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    require(alternateBytes == beforeQueryColor, @"Draw pass did not preserve copied target history");
    append(checkpoints,alternateBytes);

    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Draw before clear failed");
    [encoder endEncoding];
    pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = alternate;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0,0,1,1);
    [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Draw after clear failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Repeated draw after clear failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == (reuse ? 2u : 3u), @"Clear boundary did not restart draw pass reuse");
    [alternate getBytes:alternateBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    for (size_t i = 0; i < 256; i++)
        require(alternateBytes[i*4] == 0 && alternateBytes[i*4+1] == 0 && alternateBytes[i*4+2] == 255 && alternateBytes[i*4+3] == 255,
                @"Draw pass did not preserve cleared target history");
    append(checkpoints,alternateBytes);

    // Fractional additive writes must retain the per-draw UNorm store boundary.
    // Two separately stored .49/255 contributions each round to zero; a later
    // ordinary draw run may reuse its own pass after those blended draws.
    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = alternate;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0,0,0,0);
    [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
    HaloMetalDraw rounded = alternateDraw; rounded.depthStencil = nil;
    rounded.state.depth_enabled = rounded.state.depth_write = rounded.state.stencil_enabled = 0;
    rounded.state.color_write_mask = 15; rounded.state.blend_enabled = 1;
    rounded.state.blend_source = rounded.state.blend_destination = 2;
    rounded.state.blend_operation = 1;
    rounded.state.scissor[0] = rounded.state.scissor[1] = 0;
    rounded.state.scissor[2] = rounded.state.scissor[3] = 16;
    const float fraction[4] = {.49f/255,.49f/255,.49f/255,0};
    rounded.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,fraction);
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Ordinary draw before fractional blend failed");
    require(encode(encoder,rounded,command,reuse,&error), @"First fractional blend failed");
    require(encode(encoder,rounded,command,reuse,&error), @"Second fractional blend failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Ordinary draw after fractional blend failed");
    require(encode(encoder,alternateDraw,command,reuse,&error), @"Repeated ordinary draw after fractional blend failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == (reuse ? 4u : 5u), @"Blended draws lost their per-draw store boundary");
    [alternate getBytes:alternateBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    for (uint8_t value : alternateBytes) require(value == 0, @"Fractional blending changed isolated UNorm rounding");
    append(checkpoints,alternateBytes);

    // ONE/ZERO/ADD replaces only the enabled channels. Keep fractional values
    // in BGRA8 while changing masks, coverage, depth and stencil state in one
    // compatible run; the last successful writer supplies each final channel.
    description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:16 height:16 mipmapped:NO];
    description.storageMode = MTLStorageModeShared;
    description.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    id<MTLTexture> replacementColor = [device newTextureWithDescriptor:description];
    description.pixelFormat = MTLPixelFormatDepth32Float_Stencil8;
    description.storageMode = MTLStorageModePrivate; description.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> replacementDepth = [device newTextureWithDescriptor:description];
    require(replacementColor && replacementDepth, @"Replacement blend attachments failed");
    std::vector<uint8_t> replacementBytes(16*16*4);
    for (size_t i=0;i<256;i++) {
        replacementBytes[i*4]=31;replacementBytes[i*4+1]=63;
        replacementBytes[i*4+2]=127;replacementBytes[i*4+3]=191;
    }
    [replacementColor replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:replacementBytes.data() bytesPerRow:64];
    command = [queue commandBuffer]; pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.depthAttachment.texture = pass.stencilAttachment.texture = replacementDepth;
    pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.clearDepth = 1; pass.stencilAttachment.clearStencil = 3;
    [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
    HaloMetalDraw replacement = draw;
    replacement.color = replacementColor;replacement.depthStencil = replacementDepth;
    replacement.state.color_write_mask = 15;replacement.state.blend_enabled = 1;
    replacement.state.blend_source = 2;replacement.state.blend_destination = replacement.state.blend_operation = 1;
    replacement.state.scissor[0] = replacement.state.scissor[1] = 0;
    replacement.state.scissor[2] = replacement.state.scissor[3] = 12;
    const float halfZ[4]={0,0,.5f,0}, eighthZ[4]={0,0,.125f,0};
    const float replaceFirst[4]={17.49f/255,43.51f/255,97.49f/255,149.51f/255};
    const float replaceOverlap[4]={.19f,.73f,.41f,.37f};
    const float replaceRejected[4]={205.51f/255,33.49f/255,121.51f/255,9.49f/255};
    const float replaceDisjoint[4]={.91f,.27f,.63f,.49f};
    const float replaceAlpha[4]={63.51f/255,91.49f/255,11.49f/255,209.51f/255};
    replacement.vertexUniforms = uniforms(device,HaloMetalVertexUniformSize,halfZ);
    replacement.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replaceFirst);
    boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,replacement,command,reuse,&error), @"Fractional replacement blend failed");
    HaloMetalDraw overlap = replacement;
    overlap.state.color_write_mask = 3;overlap.state.scissor[0] = overlap.state.scissor[1] = 4;
    overlap.state.stencil_compare = 3;overlap.state.stencil_fail = 3;overlap.state.stencil_pass = 4;
    overlap.vertexUniforms = draw.vertexUniforms;
    overlap.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replaceOverlap);
    require(encode(encoder,overlap,command,reuse,&error), @"Overlapping masked replacement blend failed");
    HaloMetalDraw depthRejected = replacement;
    depthRejected.state.scissor[2] = depthRejected.state.scissor[3] = 4;
    depthRejected.state.stencil_compare = 3;depthRejected.state.stencil_depth_fail = 6;
    depthRejected.vertexUniforms = farther.vertexUniforms;
    depthRejected.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replaceRejected);
    require(encode(encoder,depthRejected,command,reuse,&error), @"Depth-rejected replacement blend failed");
    HaloMetalDraw disjoint = replacement;
    disjoint.state.color_write_mask = 12;disjoint.state.scissor[0] = 12;
    disjoint.state.scissor[2] = disjoint.state.scissor[3] = 4;
    disjoint.state.stencil_reference = 5;disjoint.state.stencil_write_mask = 15;
    disjoint.vertexUniforms = uniforms(device,HaloMetalVertexUniformSize,eighthZ);
    disjoint.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replaceDisjoint);
    require(encode(encoder,disjoint,command,reuse,&error), @"Disjoint masked replacement blend failed");
    HaloMetalDraw alphaOnly = overlap;
    alphaOnly.state.color_write_mask = 8;alphaOnly.state.scissor[2] = alphaOnly.state.scissor[3] = 4;
    alphaOnly.state.stencil_reference = 8;alphaOnly.state.stencil_write_mask = 15;
    alphaOnly.state.stencil_fail = 1;alphaOnly.state.stencil_pass = 6;
    alphaOnly.vertexUniforms = disjoint.vertexUniforms;
    alphaOnly.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replaceAlpha);
    require(encode(encoder,alphaOnly,command,reuse,&error), @"Alpha-only replacement blend failed");
    HaloMetalDraw stencilRejected = depthRejected;
    stencilRejected.state.scissor[0] = stencilRejected.state.scissor[1] = 8;
    stencilRejected.state.stencil_fail = 2;stencilRejected.state.stencil_write_mask = 15;
    stencilRejected.state.depth_write = 0;
    require(encode(encoder,stencilRejected,command,reuse,&error), @"Stencil-rejected replacement blend failed");
    [encoder endEncoding];complete(command);
    const NSUInteger replacementPasses = encoder.renderPassCount-boundaryPasses;
    require(replacementPasses == (reuse ? 1u : 6u), @"Replacement blend run did not retain exactly one compatible pass");
    [replacementColor getBytes:replacementBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    const auto replacementDepthBytes = readPlane(device,queue,replacementDepth,true);
    const auto replacementStencilBytes = readPlane(device,queue,replacementDepth,false);
    for (unsigned y=0;y<16;y++) for (unsigned x=0;x<16;x++) {
        uint8_t expected[4]={31,63,127,191}, stencilValue=3;
        float expectedDepth=1;
        if (x<12 && y<12) {
            expected[0]=97;expected[1]=44;expected[2]=17;expected[3]=150;
            expectedDepth=.5f;stencilValue=7;
        }
        if (x>=4 && y>=4) {
            if (x<12 && y<12) { expected[1]=186;expected[2]=48;expectedDepth=.25f;stencilValue=8; }
            else stencilValue=7;
        }
        if (x<4 && y<4) stencilValue=248;
        if (x>=12 && y<4) { expected[0]=161;expected[3]=125;expectedDepth=.125f;stencilValue=5; }
        if (x>=4 && x<8 && y>=4 && y<8) { expected[3]=210;expectedDepth=.125f;stencilValue=7; }
        if (x>=8 && x<12 && y>=8 && y<12) stencilValue=0;
        const size_t i=y*16+x;float actualDepth;
        memcpy(&actualDepth,replacementDepthBytes.data()+i*4,4);
        require(!memcmp(replacementBytes.data()+i*4,expected,4), @"BGRA8 replacement blend changed fractional color, alpha or masked history");
        require(actualDepth==expectedDepth && replacementStencilBytes[i]==stencilValue,
                @"Replacement blend changed depth/stencil pass, failure or masked writes");
    }
    append(checkpoints,replacementBytes);append(checkpoints,replacementDepthBytes);append(checkpoints,replacementStencilBytes);

    // Destination-dependent ADD must first store the preceding replacement
    // run. Each .49/255 channel then rounds to zero; retaining the blend across
    // that boundary would add the unquantized values and produce one instead.
    const float replacementFraction[4]={.49f/255,.49f/255,.49f/255,.49f/255};
    const uint32_t replacementMasks[2][2]={{15,15},{9,6}};
    NSUInteger replacementBoundaryPasses=0;
    for (const auto &masks : replacementMasks) {
        command = [queue commandBuffer];boundaryPasses = encoder.renderPassCount;
        pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = replacementColor;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0,0,0,0);
        [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
        HaloMetalDraw fractionalReplacement = rounded;
        fractionalReplacement.color = replacementColor;fractionalReplacement.state.blend_destination = 1;
        fractionalReplacement.pixelUniforms = uniforms(device,HaloMetalPixelUniformSize,replacementFraction);
        fractionalReplacement.state.color_write_mask = masks[0];
        require(encode(encoder,fractionalReplacement,command,reuse,&error), @"First replacement before fractional ADD failed");
        fractionalReplacement.state.color_write_mask = masks[1];
        require(encode(encoder,fractionalReplacement,command,reuse,&error), @"Masked replacement before fractional ADD failed");
        HaloMetalDraw destinationAdd = fractionalReplacement;
        destinationAdd.state.color_write_mask = 15;destinationAdd.state.blend_destination = 2;
        require(encode(encoder,destinationAdd,command,reuse,&error), @"Destination-dependent ADD after replacement failed");
        [encoder endEncoding];complete(command);
        const NSUInteger passes=encoder.renderPassCount-boundaryPasses;
        require(passes==(reuse ? 2u : 3u), @"Fractional ADD did not store the preceding replacement run");
        replacementBoundaryPasses+=passes;
        [replacementColor getBytes:replacementBytes.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
        for (uint8_t value : replacementBytes)
            require(value==0, @"Replacement-to-ADD boundary changed fractional RGB, alpha or masked-channel rounding");
        append(checkpoints,replacementBytes);
    }

    // A rejected draw closes an earlier active pass without adding commands;
    // another encoder can then be used safely on that command buffer.
    command = [queue commandBuffer]; boundaryPasses = encoder.renderPassCount;
    require(encode(encoder,noQuery,command,reuse,&error), @"Draw before rejection failed");
    HaloMetalDraw rejected = noQuery; rejected.state.depth_compare = 0;
    require(!encode(encoder,rejected,command,reuse,&error) && error.code == HaloMetalDrawInvalid, @"Invalid reusable draw accepted");
    blit = [command blitCommandEncoder]; require(blit != nil, @"Rejected draw left an active render pass");
    [blit endEncoding];
    require(encode(encoder,noQuery,command,reuse,&error), @"Valid draw after rejection failed");
    [encoder endEncoding]; complete(command);
    require(encoder.renderPassCount - boundaryPasses == 2, @"Rejected draw created a pass or retained its previous pass");
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    require(rgba == beforeQueryColor && readPlane(device,queue,depth,true) == beforeQueryDepth &&
            readPlane(device,queue,depth,false) == beforeQueryStencil, @"Pass boundaries changed original attachment history");
    append(checkpoints,rgba); append(checkpoints,readPlane(device,queue,depth,true));
    append(checkpoints,readPlane(device,queue,depth,false));

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
    require([encoder usedTextureMaskForDraw:invalid mask:&usedTextures error:&error] && usedTextures == 1,
            @"Used texture mask differs from sampled shader bindings");
    HaloMetalDraw edges = invalid; edges.fragmentFunction = [library newFunctionWithName:@"sampledEdgesFragment"];
    edges.textures[3] = edges.textures[0]; edges.samplers[3] = edges.samplers[0];
    require([encoder usedTextureMaskForDraw:edges mask:&usedTextures error:&error] && usedTextures == 9,
            @"Sparse used texture mask lost the last stage");
    // Each public entry must recheck mutable draw resources after a pipeline's
    // immutable requirements have been cached. Failed mask queries leave the
    // caller's output untouched, just as a failed original reflection walk did.
    auto rejectedByEveryEntry = [&](const HaloMetalDraw &candidate, HaloMetalDrawError code, NSString *message) {
        require(![encoder prepareDraw:candidate error:&error] && error.code == code &&
                [error.localizedDescription isEqualToString:message], @"Cached prepare validation changed its error");
        usedTextures = UINT32_MAX;
        require(![encoder usedTextureMaskForDraw:candidate mask:&usedTextures error:&error] &&
                usedTextures == UINT32_MAX && error.code == code && [error.localizedDescription isEqualToString:message],
                @"Cached texture mask validation changed its error or output");
        require(!encode(encoder,candidate,[queue commandBuffer],reuse,&error) && error.code == code &&
                [error.localizedDescription isEqualToString:message], @"Cached encode validation changed its error");
    };
    HaloMetalDraw changed = edges; changed.textures[3] = nil;
    rejectedByEveryEntry(changed,HaloMetalDrawInvalid,@"Used original texture is absent, mismatched or aliases a draw attachment");
    changed = edges; changed.samplers[3] = nil;
    rejectedByEveryEntry(changed,HaloMetalDrawInvalid,@"Used original sampler is absent or mismatched");
    changed = edges; changed.textures[3] = color;
    rejectedByEveryEntry(changed,HaloMetalDrawInvalid,@"Used original texture is absent, mismatched or aliases a draw attachment");
    changed = draw; changed.fragmentFunction = [library newFunctionWithName:@"unsupportedBufferFragment"];
    rejectedByEveryEntry(changed,HaloMetalDrawUnsupported,@"Shader requires an unsupported original buffer binding");
    changed.fragmentFunction = [library newFunctionWithName:@"oversizedBufferFragment"];
    rejectedByEveryEntry(changed,HaloMetalDrawInvalid,@"Shader uniform/input structure exceeds the captured original buffer");
    changed.fragmentFunction = [library newFunctionWithName:@"unsupportedTextureFragment"];
    rejectedByEveryEntry(changed,HaloMetalDrawUnsupported,@"Shader requires an unsupported original texture binding");
    require(!encode(encoder,draw,command,reuse,&error), @"Submitted command buffer accepted");
    [encoder removePipelinesForVertexFunction:draw.vertexFunction fragmentFunction:nil];
    require([encoder prepareDraw:draw error:&error], error.localizedDescription ?: @"Cache eviction lost valid original program");
    require([encoder usedTextureMaskForDraw:edges mask:&usedTextures error:&error] && usedTextures == 9,
            @"Cache eviction lost sparse texture requirements");
    const NSUInteger creationsBeforeClear = encoder.pipelineCreationCount;
    const uint64_t nanosecondsBeforeClear = encoder.pipelineCreationNanoseconds;
    [encoder clearCaches];
    require(encoder.pipelineCreationCount == creationsBeforeClear && encoder.pipelineCreationNanoseconds == nanosecondsBeforeClear,
            @"Cache clear reset pipeline diagnostic counters");
    require([encoder usedTextureMaskForDraw:edges mask:&usedTextures error:&error] && usedTextures == 9,
            @"Cache clear lost sparse texture requirements");
    require(encoder.pipelineCreationCount == creationsBeforeClear + 1 && encoder.pipelineCreationNanoseconds > nanosecondsBeforeClear,
            @"Pipeline recreation after cache clear did not accumulate its timing");
    // This contract prevents GPU vertex pulling from reading outside the
    // immutable captured slice, while preserving the expanded draw reference.
    halo_metal_compact_vertex_input compactInput = {};
    compactInput.version = HALO_METAL_COMPACT_VERTEX_VERSION;
    compactInput.vertex_count = 3; compactInput.element_count = 1;
    compactInput.elements[0] = {0,0x42,sizeof(compactInput),16};
    std::vector<uint8_t> compactBytes(sizeof(compactInput) + sizeof(positions) + 16);
    memcpy(compactBytes.data()+16,&compactInput,sizeof(compactInput));
    memcpy(compactBytes.data()+16+sizeof(compactInput),positions,sizeof(positions));
    HaloMetalDraw compact = draw;
    compact.vertexFunction = [library newFunctionWithName:@"compactVertex"];
    compact.vertices = [device newBufferWithBytes:compactBytes.data() length:compactBytes.size() options:MTLResourceStorageModeShared];
    compact.compactVertices = true; compact.vertexBytes = compactBytes.size()-16;
    require([encoder prepareDraw:compact error:&error], error.localizedDescription ?: @"Compact draw preparation failed");
    auto privateIndices = compact;
    privateIndices.indices = [device newBufferWithLength:draw.indices.length options:MTLResourceStorageModePrivate];
    require(privateIndices.indices != nil,@"Private compact index fixture allocation failed");
    const NSUInteger compactPasses = encoder.renderPassCount;
    require(!encode(encoder,privateIndices,[queue commandBuffer],reuse,&error) && error.code == HaloMetalDrawInvalid &&
            encoder.renderPassCount == compactPasses,@"Unchecked private compact indices reached a GPU encoder");
    auto rejectCompact = [&](const halo_metal_compact_vertex_input &candidate, NSUInteger span, NSString *message) {
        auto rejected = compact;
        std::vector<uint8_t> bad = compactBytes;memcpy(bad.data()+16,&candidate,sizeof(candidate));
        rejected.vertices = [device newBufferWithBytes:bad.data() length:bad.size() options:MTLResourceStorageModeShared];
        rejected.vertexBytes = span;
        const NSUInteger passes = encoder.renderPassCount;
        require(!encode(encoder,rejected,[queue commandBuffer],reuse,&error) && error.code == HaloMetalDrawInvalid &&
                encoder.renderPassCount == passes,message);
    };
    rejectCompact(compactInput,sizeof(compactInput)-1,@"Truncated compact prefix reached a GPU encoder");
    auto oversized = compact;
    oversized.vertices = [device newBufferWithLength:NSUInteger(HALO_METAL_MAX_PACKET)+32 options:MTLResourceStorageModeShared];
    require(oversized.vertices != nil,@"Oversized compact fixture allocation failed");
    memcpy(oversized.vertices.contents,compactBytes.data(),compactBytes.size());
    oversized.vertexBytes = oversized.vertices.length - oversized.vertexOffset;
    require(!encode(encoder,oversized,[queue commandBuffer],reuse,&error) && error.code == HaloMetalDrawInvalid &&
            encoder.renderPassCount == compactPasses,@"Oversized valid compact buffer reached a GPU encoder");
    rejectCompact(compactInput,compact.vertexBytes-1,@"Truncated compact source span reached a GPU encoder");
    auto badCompact = compactInput;badCompact.version++;
    rejectCompact(badCompact,compact.vertexBytes,@"Unknown compact version accepted");
    badCompact = compactInput;badCompact.elements[0].offset = 512;
    rejectCompact(badCompact,compact.vertexBytes,@"Compact descriptor could read prefix bytes");
    badCompact = compactInput;badCompact.elements[0].stride = UINT32_MAX;
    rejectCompact(badCompact,compact.vertexBytes,@"Overflowing compact stride accepted");
    badCompact = compactInput;badCompact.elements[0].type = 0x02;
    rejectCompact(badCompact,compact.vertexBytes,@"Inactive compact descriptor accepted");
    badCompact = compactInput;badCompact.elements[0].type = 0xff;
    rejectCompact(badCompact,compact.vertexBytes,@"Unknown compact descriptor type accepted");
    badCompact = compactInput;badCompact.element_count = 2;badCompact.elements[1] = badCompact.elements[0];
    rejectCompact(badCompact,compact.vertexBytes,@"Duplicate compact register accepted");
    badCompact = compactInput;badCompact.fixed[1][0] = std::numeric_limits<float>::infinity();
    rejectCompact(badCompact,compact.vertexBytes,@"Nonfinite compact fallback accepted");
    auto nonfinite = compact;std::vector<uint8_t> nonfiniteBytes = compactBytes;
    const float infinity = std::numeric_limits<float>::infinity();
    memcpy(nonfiniteBytes.data()+16+sizeof(compactInput),&infinity,sizeof(infinity));
    nonfinite.vertices = [device newBufferWithBytes:nonfiniteBytes.data() length:nonfiniteBytes.size() options:MTLResourceStorageModeShared];
    require(![encoder prepareDraw:nonfinite error:&error],@"Nonfinite effective compact float accepted");
    auto packedInput = compactInput;packedInput.packed_mask = 2;packedInput.element_count = 2;
    packedInput.elements[1] = {1,0x16,(uint32_t)compact.vertexBytes,0};
    auto packedBytes = compactBytes;packedBytes.resize(packedBytes.size()+4);
    memcpy(packedBytes.data()+16,&packedInput,sizeof(packedInput));
    const uint32_t packedNaN = UINT32_C(0xffffffff);
    memcpy(packedBytes.data()+16+compact.vertexBytes,&packedNaN,sizeof(packedNaN));
    auto packed = compact;packed.packedMask = 2;packed.vertexBytes += 4;
    packed.vertices = [device newBufferWithBytes:packedBytes.data() length:packedBytes.size() options:MTLResourceStorageModeShared];
    require([encoder prepareDraw:packed error:&error],@"Instruction-visible compact packed bits were rejected as nonfinite floats");
    const uint32_t compactIndices[3] = {0,1,2}, invalidCompactIndices[3] = {0,1,3};
    require(!HaloMetalGeometry::create(device,compactBytes.data()+16,(uint32_t)compact.vertexBytes,3,
            invalidCompactIndices,3,0),@"Immutable factory accepted an out-of-range index");
    auto geometry = HaloMetalGeometry::create(device,compactBytes.data()+16,(uint32_t)compact.vertexBytes,3,compactIndices,3,0);
    require(geometry != nullptr,@"Immutable compact geometry allocation failed");
    HaloMetalDraw immutable = compact;
    immutable.vertices = geometry->vertices();immutable.indices = geometry->indices();
    immutable.vertexOffset = immutable.indexOffset = 0;immutable.geometry = geometry;
    require([encoder prepareDraw:immutable error:&error],@"Validated immutable private input rejected");
    auto mismatched = immutable;mismatched.vertexCount++;
    require(![encoder prepareDraw:mismatched error:&error],@"Immutable proof accepted mismatched bounds");
    mismatched = immutable;mismatched.vertices = compact.vertices;
    require(![encoder prepareDraw:mismatched error:&error],@"Immutable proof accepted another buffer");
    mismatched = immutable;mismatched.geometry.reset();
    require(![encoder prepareDraw:mismatched error:&error],@"Private input without proof bypassed validation");
    const NSUInteger beforeUploadPasses = encoder.renderPassCount;
    require(!encode(encoder,immutable,[queue commandBuffer],reuse,&error) && error.code == HaloMetalDrawInvalid &&
            encoder.renderPassCount == beforeUploadPasses,@"Uninitialized immutable buffers reached a GPU encoder");
    // Mutating the original source after construction cannot alter its proof.
    memset(compactBytes.data()+16,0,compactBytes.size()-16);
    auto pixels = [&](HaloMetalDraw candidate) { @autoreleasepool {
        [color replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:initial.data() bytesPerRow:64];
        candidate.depthStencil = nil;candidate.state.depth_enabled = candidate.state.depth_write = candidate.state.stencil_enabled = 0;
        candidate.state.color_write_mask = 15;
        auto command = [queue commandBuffer];
        if (candidate.geometry) {
            require(candidate.geometry->upload(command),@"Immutable geometry upload failed");
            require(!candidate.geometry->retireUpload(command),@"Unsubmitted upload manufactured completed readiness");
            require(!candidate.geometry->retireUpload(clear),@"Unrelated completed command retired an immutable upload");
        }
        require(encode(encoder,candidate,command,reuse,&error),error.localizedDescription ?: @"Geometry comparison failed");
        [encoder endEncoding];complete(command);
        if (candidate.geometry) {
            require(candidate.geometry->retireUpload(command),@"Exact completed immutable upload failed retirement");
            require(!candidate.geometry->retireUpload(nil),@"Missing command retired an immutable upload");
            command = nil;
        }
        std::vector<uint8_t> result(16*16*4);
        [color getBytes:result.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
        return result;
    } };
    const auto expandedPixels = pixels(draw), compactPixels = pixels(compact);
    require(compactPixels == expandedPixels,@"Compact vertex pulling changed expanded reference pixels");
    require(pixels(immutable) == compactPixels,@"Immutable geometry changed compact reference pixels");
    require(geometry->readyForDraw([queue commandBuffer]),@"Completed immutable input lost upload readiness");
    for (unsigned y = 4; y < 12; y++) for (unsigned x = 4; x < 12; x++) {
        const size_t pixel = (y*16+x)*4;
        require(compactPixels[pixel] == 255 && compactPixels[pixel+1] == 0 &&
                compactPixels[pixel+2] == 0 && compactPixels[pixel+3] == 255,@"Compact test drew no original red geometry");
    }
    append(checkpoints,compactPixels);

    // The same buffer identities carry different geometry/uniform offsets.
    // Keep the whole run in one pass so stale offsets, textures, samplers or
    // pipeline state change the independent isolated-mode reference image.
    [color replaceRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0 withBytes:initial.data() bytesPerRow:64];
    HaloMetalDraw bound = draw; bound.depthStencil = nil;
    bound.state.depth_enabled = bound.state.depth_write = bound.state.stencil_enabled = 0;
    bound.state.color_write_mask = 15;
    bound.state.scissor[0] = bound.state.scissor[1] = 0;
    bound.state.scissor[2] = 4; bound.state.scissor[3] = 16;
    std::vector<uint8_t> alternateVertices(HaloMetalVertexStride*6);
    const float smallPositions[3][4] = {{-1,-1,0,1},{1,-1,0,1},{-1,1,0,1}};
    for (unsigned i = 0; i < 3; i++) {
        memcpy(alternateVertices.data()+i*HaloMetalVertexStride,positions[i],16);
        memcpy(alternateVertices.data()+(i+3)*HaloMetalVertexStride,smallPositions[i],16);
    }
    bound.vertices = [device newBufferWithBytes:alternateVertices.data() length:alternateVertices.size()
        options:MTLResourceStorageModeShared];
    bound.vertexOffset = 0;
    std::vector<uint8_t> alternateVS(HaloMetalVertexUniformSize*2), alternatePS(HaloMetalPixelUniformSize*4);
    const float shifted[4] = {.5f,0,.25f,0}, blue[4] = {0,0,1,1}, white[4] = {1,1,1,1};
    memcpy(alternateVS.data(),firstZ,16);memcpy(alternateVS.data()+HaloMetalVertexUniformSize,shifted,16);
    memcpy(alternatePS.data(),red,16);memcpy(alternatePS.data()+HaloMetalPixelUniformSize,green,16);
    memcpy(alternatePS.data()+HaloMetalPixelUniformSize*2,blue,16);
    memcpy(alternatePS.data()+HaloMetalPixelUniformSize*3,white,16);
    bound.vertexUniforms = [device newBufferWithBytes:alternateVS.data() length:alternateVS.size() options:MTLResourceStorageModeShared];
    bound.pixelUniforms = [device newBufferWithBytes:alternatePS.data() length:alternatePS.size() options:MTLResourceStorageModeShared];
    bound.vertexUniformOffset = bound.pixelUniformOffset = 0;
    description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:2 height:2 mipmapped:NO];
    description.storageMode = MTLStorageModeShared;description.usage = MTLTextureUsageShaderRead;
    auto checker = [device newTextureWithDescriptor:description], solid = [device newTextureWithDescriptor:description];
    const uint8_t checkerBytes[16] = {255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255};
    const uint8_t solidBytes[16] = {0,255,0,255,0,255,0,255,0,255,0,255,0,255,0,255};
    [checker replaceRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0 withBytes:checkerBytes bytesPerRow:8];
    [solid replaceRegion:MTLRegionMake2D(0,0,2,2) mipmapLevel:0 withBytes:solidBytes bytesPerRow:8];
    auto nearestDescription = [MTLSamplerDescriptor new], linearDescription = [MTLSamplerDescriptor new];
    linearDescription.minFilter = linearDescription.magFilter = MTLSamplerMinMagFilterLinear;
    auto nearest = [device newSamplerStateWithDescriptor:nearestDescription], linear = [device newSamplerStateWithDescriptor:linearDescription];
    require(bound.vertices && bound.vertexUniforms && bound.pixelUniforms && checker && solid && nearest && linear,
            @"Dynamic binding fixture allocation failed");
    command = [queue commandBuffer];
    require(encode(encoder,bound,command,reuse,&error), @"First dynamic binding draw failed");
    bound.state.scissor[0] = 4;bound.vertexUniformOffset = HaloMetalVertexUniformSize;
    bound.pixelUniformOffset = HaloMetalPixelUniformSize;
    require(encode(encoder,bound,command,reuse,&error), @"Dynamic uniform offsets draw failed");
    bound.state.scissor[0] = 8;bound.vertexOffset = HaloMetalVertexStride*3;
    bound.vertexUniformOffset = 0;bound.pixelUniformOffset = HaloMetalPixelUniformSize*2;
    require(encode(encoder,bound,command,reuse,&error), @"Dynamic geometry offset draw failed");
    bound.state.scissor[0] = 12;bound.vertexOffset = 0;bound.pixelUniformOffset = HaloMetalPixelUniformSize*3;
    bound.fragmentFunction = [library newFunctionWithName:@"sampledFragment"];
    bound.textures[0] = checker;bound.samplers[0] = nearest;
    require(encode(encoder,bound,command,reuse,&error), @"Dynamic sampled pipeline draw failed");
    bound.state.scissor[0] = 0;bound.state.scissor[3] = 8;bound.textures[0] = solid;
    require(encode(encoder,bound,command,reuse,&error), @"Dynamic texture draw failed");
    bound.state.scissor[0] = 4;bound.textures[0] = checker;bound.samplers[0] = linear;
    require(encode(encoder,bound,command,reuse,&error), @"Dynamic sampler draw failed");
    bound.state.scissor[0] = 12;bound.state.scissor[3] = 4;
    bound.fragmentFunction = draw.fragmentFunction;bound.pixelUniformOffset = HaloMetalPixelUniformSize*2;
    bound.textures[0] = nil;bound.samplers[0] = nil;
    require(encode(encoder,bound,command,reuse,&error), @"Removing sampled bindings failed");
    const NSUInteger repeatSets = encoder.bindingSetCount, repeatSkips = encoder.bindingSkipCount;
    require(encode(encoder,bound,command,reuse,&error), @"Repeating exact bindings failed");
    require(cached ? (encoder.bindingSetCount == repeatSets && encoder.bindingSkipCount > repeatSkips) :
            (encoder.bindingSetCount > repeatSets && encoder.bindingSkipCount == repeatSkips),
            @"Exact repeated bindings did not respect cache selection");
    if (cached) {
        encoder.cacheBindingsEnabled = NO;encoder.cacheBindingsEnabled = YES;
        require(encode(encoder,bound,command,reuse,&error) && encoder.bindingSetCount > repeatSets,
                @"Toggling binding cache retained stale setter state");
    }
    [encoder endEncoding];complete(command);
    [color getBytes:rgba.data() bytesPerRow:64 fromRegion:MTLRegionMake2D(0,0,16,16) mipmapLevel:0];
    for (unsigned y = 8; y < 16; y++) for (unsigned x = 0; x < 4; x++) {
        const size_t pixel = (y*16+x)*4;
        require(rgba[pixel] == 255 && rgba[pixel+1] == 0 && rgba[pixel+2] == 0 && rgba[pixel+3] == 255,
                @"Dynamic bindings drew no reference red region");
    }
    append(checkpoints,rgba);
    if (argc == 3) {
        FILE *file = fopen(argv[2],"wb"); require(file != nullptr, @"Checkpoint output failed");
        require(fwrite(checkpoints.data(),1,checkpoints.size(),file) == checkpoints.size() && fclose(file) == 0,
                @"Checkpoint output was incomplete");
    }
    printf("{\"complete\":true,\"color_depth_stencil_history\":true,\"state_and_resource_validation\":true,"
        "\"visibility_readonly_count\":64,\"visibility_occluded_count\":0,\"visibility_boolean\":1,"
        "\"visibility_offset_validation\":true,\"cpu_query_timing_verified\":false,"
        "\"bgra8_replacement_history\":true,\"replacement_store_boundary\":true,"
        "\"replacement_blend_draws\":6,\"replacement_blend_passes\":%lu,\"replacement_boundary_cases\":2,\"replacement_boundary_passes\":%lu,"
        "\"pass_reuse\":%s,\"binding_cache\":%s,\"binding_sets\":%lu,\"binding_skips\":%lu,"
        "\"render_passes\":%lu,\"checkpoint_bytes\":%zu}\n",
        (unsigned long)replacementPasses,(unsigned long)replacementBoundaryPasses,
        reuse ? "true" : "false",cached ? "true" : "false",(unsigned long)encoder.bindingSetCount,
        (unsigned long)encoder.bindingSkipCount,(unsigned long)encoder.renderPassCount,checkpoints.size());
    return 0;
} }
