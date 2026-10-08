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
static BOOL encode(HaloMetalDrawEncoder *encoder, const HaloMetalDraw &draw,
                   id<MTLCommandBuffer> command, bool reuse, NSError **error) {
    return reuse ? [encoder encodeDraw:draw commandBuffer:command reusePass:YES error:error] :
                   [encoder encodeDraw:draw commandBuffer:command error:error];
}
static void append(std::vector<uint8_t> &result, const std::vector<uint8_t> &bytes) {
    result.insert(result.end(),bytes.begin(),bytes.end());
}
int main(int argc, const char **argv) { @autoreleasepool {
    const bool reuse = argc > 1 && !strcmp(argv[1],"reuse");
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
    require([encoder prepareDraw:draw error:&error], error.localizedDescription ?: @"First draw preparation failed");
    uint32_t usedTextures = UINT32_MAX;
    require([encoder usedTextureMaskForDraw:draw mask:&usedTextures error:&error] && usedTextures == 0,
            @"Untextured draw returned used textures");
    HaloMetalDraw farther = draw;
    const float fartherZ[4] = {0, 0, .75f, 0}, green[4] = {0, 1, 0, 1};
    farther.vertexUniforms = uniforms(device, HaloMetalVertexUniformSize, fartherZ);
    farther.pixelUniforms = uniforms(device, HaloMetalPixelUniformSize, green);
    id<MTLCommandBuffer> command = [queue commandBuffer];
    require(encode(encoder,draw,command,reuse,&error), error.localizedDescription ?: @"First draw encoding failed");
    require(encode(encoder,farther,command,reuse,&error), error.localizedDescription ?: @"Second draw encoding failed");
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
    [encoder clearCaches];
    require([encoder usedTextureMaskForDraw:edges mask:&usedTextures error:&error] && usedTextures == 9,
            @"Cache clear lost sparse texture requirements");
    if (argc == 3) {
        FILE *file = fopen(argv[2],"wb"); require(file != nullptr, @"Checkpoint output failed");
        require(fwrite(checkpoints.data(),1,checkpoints.size(),file) == checkpoints.size() && fclose(file) == 0,
                @"Checkpoint output was incomplete");
    }
    printf("{\"complete\":true,\"color_depth_stencil_history\":true,\"state_and_resource_validation\":true,"
        "\"visibility_readonly_count\":64,\"visibility_occluded_count\":0,\"visibility_boolean\":1,"
        "\"visibility_offset_validation\":true,\"cpu_query_timing_verified\":false,"
        "\"pass_reuse\":%s,\"render_passes\":%lu,\"checkpoint_bytes\":%zu}\n",
        reuse ? "true" : "false",(unsigned long)encoder.renderPassCount,checkpoints.size());
    return 0;
} }
