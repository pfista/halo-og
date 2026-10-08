/* The production compact decoder runs on Metal and is compared byte-for-byte
 * with the established CPU vertex-fetch path. No game or scene substitutes. */
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import "../host/metal_draw_encoder.h"
#include "../include/halo_metal_vertex_input.h"
#include "../../linux/src/metal_vertex_fetch.h"
#include "../../linux/src/xgpu_vertex_decode_msl.h"
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <vector>

static void require(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
struct Fixture {
    halo_metal_compact_vertex_input header{};
    metal_vertex_declaration declaration{};
    std::vector<uint8_t> bytes;
    metal_vertex_stream streams[16]{};
    uint32_t count;
};
static uint32_t type_bytes(uint32_t type) {
    switch (type) {
    case 0x02: return 0;
    case 0x12: return 4; case 0x22: return 8; case 0x32: case 0x72: return 12; case 0x42: return 16;
    case 0x40: case 0x16: return 4;
    case 0x11: case 0x15: return 2; case 0x21: case 0x25: return 4;
    case 0x31: case 0x35: return 6; case 0x41: case 0x45: return 8;
    case 0x14: return 1; case 0x24: return 2; case 0x34: return 3; case 0x44: return 4;
    default: throw std::runtime_error("Unknown fixture format");
    }
}
static Fixture fixture(uint32_t type, uint32_t count, bool zero_stride = false, bool unbound = false) {
    Fixture f{}; f.count = count;
    const uint32_t bytes = type_bytes(type), stride = zero_stride ? 0 : bytes + 3;
    f.header.version = HALO_METAL_COMPACT_VERTEX_VERSION;
    f.header.vertex_count = count;
    f.header.packed_mask = f.declaration.packed_mask = type == 0x16 ? 1u << 5 : 0;
    f.declaration.element_count = 1;
    f.declaration.elements[0] = {5, 2, type, bytes, 1};
    for (uint32_t reg = 0; reg < 16; reg++) {
        f.header.fixed[reg][0] = float(reg) + 0.25f;
        f.header.fixed[reg][1] = -0.0f;
        f.header.fixed[reg][2] = -float(reg);
        f.header.fixed[reg][3] = 1.0f;
    }
    if (type == 0x16) memset(f.header.fixed[5], 0, 16);
    const size_t size = sizeof(f.header) + 1 + size_t(count - 1) * stride + bytes;
    f.bytes.resize(size, 0);
    if (!unbound && bytes) {
        f.header.element_count = 1;
        f.header.elements[0] = {5, type, uint32_t(sizeof(f.header) + 1), stride};
        for (uint32_t vertex = 0; vertex < (zero_stride ? 1u : count); vertex++) {
            uint8_t *p = f.bytes.data() + sizeof(f.header) + 1 + size_t(vertex) * stride;
            if (type == 0x16) {
                const uint32_t patterns[] = {0xFFF80001u, 0x7FC12345u, 0xFFFFFFFFu, 0u};
                memcpy(p, &patterns[vertex % 4], 4);
            } else for (uint32_t component = 0; component < (type == 0x72 ? 3 : type >> 4); component++) {
                if ((type & 15) == 2) {
                    const uint32_t patterns[] = {0x80000000u, 0x00000000u, 0x00000001u, 0x00800000u,
                        0x3eaaaaabu, 0xbf400000u, 0x3f800000u, 0xc0800000u};
                    memcpy(p + component * 4, &patterns[(vertex + component) % 8], 4);
                } else if ((type & 15) == 1 || (type & 15) == 5) {
                    const int16_t value = int16_t((vertex + component * 16381u) & 65535u);
                    memcpy(p + component * 2, &value, 2);
                } else p[component] = uint8_t(vertex + component * 61);
            }
        }
        f.streams[2] = {f.bytes.data() + sizeof(f.header), f.bytes.size() - sizeof(f.header), stride};
    }
    memcpy(f.bytes.data(), &f.header, sizeof(f.header));
    return f;
}
static Fixture mixed_fixture() {
    Fixture f = fixture(0x12, 513);
    const uint32_t stride = 83;
    f.header.element_count = f.declaration.element_count = 16;
    f.bytes.assign(sizeof(f.header) + size_t(f.count) * stride, 0);
    for (uint32_t index = 0; index < 16; index++) {
        const uint32_t reg = (index * 7) & 15, offset = index * 5 + 1;
        f.declaration.elements[index] = {reg, 2, 0x12, 4, offset};
        f.header.elements[index] = {reg, 0x12, uint32_t(sizeof(f.header)) + offset, stride};
        for (uint32_t vertex = 0; vertex < f.count; vertex++) {
            const float value = float(vertex) + float(reg) * 0.125f;
            memcpy(f.bytes.data() + sizeof(f.header) + size_t(vertex) * stride + offset, &value, 4);
        }
    }
    f.streams[2] = {f.bytes.data() + sizeof(f.header), f.bytes.size() - sizeof(f.header), stride};
    memcpy(f.bytes.data(), &f.header, sizeof(f.header));
    return f;
}
static size_t compare(id<MTLDevice> device, id<MTLCommandQueue> queue,
                      id<MTLComputePipelineState> pipeline, Fixture &f) {
    // Moving the fixture can move its vector owner; rebuild the source pointer.
    if (f.streams[2].pointer) f.streams[2].pointer = f.bytes.data() + sizeof(f.header);
    std::vector<uint8_t> expected(size_t(f.count) * 256);
    require(metal_vertex_fetch(&f.declaration, f.streams, f.header.fixed, 0, f.count,
        expected.data(), expected.size()) == METAL_VERTEX_OK, "CPU fixture fetch failed");
    auto input = [device newBufferWithBytes:f.bytes.data() length:f.bytes.size() options:MTLResourceStorageModeShared];
    auto values = [device newBufferWithLength:expected.size() options:MTLResourceStorageModeShared];
    auto packed = [device newBufferWithLength:size_t(f.count) * 64 options:MTLResourceStorageModeShared];
    require(input && values && packed, "GPU fixture allocation failed");
    auto command = [queue commandBuffer]; auto encoder = [command computeCommandEncoder];
    [encoder setComputePipelineState:pipeline];
    [encoder setBuffer:input offset:0 atIndex:0];
    [encoder setBuffer:values offset:0 atIndex:1];
    [encoder setBuffer:packed offset:0 atIndex:2];
    const NSUInteger width = pipeline.threadExecutionWidth;
    [encoder dispatchThreads:MTLSizeMake(f.count, 1, 1) threadsPerThreadgroup:MTLSizeMake(width, 1, 1)];
    [encoder endEncoding]; [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted, "GPU fixture command failed");
    const uint8_t *actual = (const uint8_t *)values.contents;
    const uint32_t *actual_packed = (const uint32_t *)packed.contents;
    size_t comparisons = 0;
    for (uint32_t vertex = 0; vertex < f.count; vertex++) for (uint32_t reg = 0; reg < 16; reg++) {
        const uint8_t *want = expected.data() + size_t(vertex) * 256 + reg * 16;
        if (f.header.packed_mask & (1u << reg)) {
            uint32_t bits; memcpy(&bits, want, 4);
            require(bits == actual_packed[size_t(vertex) * 16 + reg], "Packed raw word changed");
            comparisons++;
        } else for (uint32_t component = 0; component < 4; component++) {
            uint32_t a, b;
            memcpy(&a, actual + size_t(vertex) * 256 + reg * 16 + component * 4, 4);
            memcpy(&b, want + component * 4, 4);
            if (a != b) {
                fprintf(stderr, "decode mismatch: type %02x vertex %u reg %u component %u GPU %08x CPU %08x\n",
                    f.declaration.elements[0].type, vertex, reg, component, a, b);
                throw std::runtime_error("Decoded float register bits changed");
            }
            comparisons++;
        }
    }
    return comparisons;
}
struct RenderUniforms {
    float c[192][4], viewport_scale[4], viewport_offset[4];
    float point_size, screen_offset, padding[2];
};
static_assert(sizeof(RenderUniforms) == HaloMetalVertexUniformSize, "Original vertex uniform size");
static std::vector<uint8_t> render(id<MTLDevice> device, id<MTLCommandQueue> queue, MTLCompileOptions *options,
    NSString *source, bool compact, MTLPixelFormat format, const std::vector<uint8_t> &input,
    const uint32_t indices[3], const RenderUniforms &uniforms) {
    // Probe only the original program's interpolants. Both paths use this same
    // fragment function, while the NV2A vertex sources remain unmodified.
    source = [source stringByAppendingString:@"\nfragment float4 render_fragment(XgpuVaryings in [[stage_in]]) {\n"
        "return float4(clamp(in.xD0.xyz * 0.375 + in.xD1.xyz * 0.125 + in.xT0.xyz * 0.125 + "
        "in.xT1.xyz * 0.125 + in.xT2.xyz * 0.25, float3(0.0), float3(1.0)), 1.0); }\n"];
    NSError *error = nil;
    auto library = [device newLibraryWithSource:source options:options error:&error];
    if (!library) fprintf(stderr, "%s\n", error.description.UTF8String);
    require(library != nil, "Original NV2A render shader compilation failed");
    auto description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format width:64 height:64 mipmapped:NO];
    description.storageMode = MTLStorageModeShared; description.usage = MTLTextureUsageRenderTarget;
    auto color = [device newTextureWithDescriptor:description];
    description.pixelFormat = MTLPixelFormatDepth32Float_Stencil8; description.storageMode = MTLStorageModePrivate;
    auto depth = [device newTextureWithDescriptor:description];
    require(color && depth, "Original NV2A render attachment allocation failed");
    HaloMetalDraw draw;
    draw.vertexFunction = [library newFunctionWithName:@"xgpu_vertex"];
    draw.fragmentFunction = [library newFunctionWithName:@"render_fragment"];
    draw.color = color; draw.depthStencil = depth;
    draw.vertexCount = draw.indexCount = 3; draw.packedMask = 2;
    draw.compactVertices = compact; draw.vertexBytes = compact ? input.size() : 0;
    draw.vertices = [device newBufferWithBytes:input.data() length:input.size() options:MTLResourceStorageModeShared];
    draw.indices = [device newBufferWithBytes:indices length:12 options:MTLResourceStorageModeShared];
    draw.vertexUniforms = [device newBufferWithBytes:&uniforms length:sizeof(uniforms) options:MTLResourceStorageModeShared];
    draw.pixelUniforms = [device newBufferWithLength:HaloMetalPixelUniformSize options:MTLResourceStorageModeShared];
    require(draw.vertices && draw.indices && draw.vertexUniforms && draw.pixelUniforms,
        "Original NV2A render input allocation failed");
    memset(draw.pixelUniforms.contents, 0, HaloMetalPixelUniformSize);
    auto &state = draw.state;
    state.color_write_mask = 15; state.blend_source = 2; state.blend_destination = state.blend_operation = 1;
    state.depth_enabled = state.depth_write = 1; state.depth_compare = 2;
    state.stencil_compare = 8; state.stencil_fail = state.stencil_depth_fail = state.stencil_pass = 1;
    state.viewport[2] = state.viewport[3] = 64; state.viewport[5] = 1;
    state.scissor[2] = state.scissor[3] = 64;
    auto command = [queue commandBuffer];
    auto pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = color;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear; pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0.03125, 0.0625, 0.09375, 1);
    pass.depthAttachment.texture = pass.stencilAttachment.texture = depth;
    pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.clearDepth = 1;
    [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
    auto encoder = [[HaloMetalDrawEncoder alloc] initWithDevice:device];
    const bool encoded = [encoder encodeDraw:draw commandBuffer:command error:&error];
    if (!encoded) fprintf(stderr, "%s\n", error.description.UTF8String);
    require(encoded, "Original NV2A production draw encoding failed");
    auto readback = [device newBufferWithLength:16384 options:MTLResourceStorageModeShared];
    require(readback != nil, "Original NV2A depth readback allocation failed");
    auto blit = [command blitCommandEncoder];
    [blit copyFromTexture:depth sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
        sourceSize:MTLSizeMake(64, 64, 1) toBuffer:readback destinationOffset:0
        destinationBytesPerRow:256 destinationBytesPerImage:16384 options:MTLBlitOptionDepthFromDepthStencil];
    [blit endEncoding]; [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted, "Original NV2A render command failed");
    std::vector<uint8_t> result(32768);
    [color getBytes:result.data() bytesPerRow:256 fromRegion:MTLRegionMake2D(0, 0, 64, 64) mipmapLevel:0];
    memcpy(result.data() + 16384, readback.contents, 16384);
    return result;
}
static size_t render_parity(id<MTLDevice> device, id<MTLCommandQueue> queue, MTLCompileOptions *options, NSString *folder) {
    // Original program37 copies packed/short/byte inputs into color and texture
    // outputs after transforming FLOAT4 positions with the original constants.
    // Nonzero base and sparse order exercise the production index rebasing.
    const uint16_t original_indices[3] = {2, 4, 3};
    uint32_t indices[3]; struct metal_vertex_index_plan plan{};
    require(metal_vertex_indices(5, original_indices, 6, 3, 0, 5, indices, 12, &plan) == METAL_VERTEX_OK,
        "Original NV2A triangle rebasing failed");
    require(plan.source_first == 7 && plan.source_count == 3 && indices[0] == 0 && indices[1] == 2 && indices[2] == 1,
        "Original NV2A indexed fixture has the wrong source window");
    const uint32_t stride = 37;
    std::vector<uint8_t> raw(10 * stride, 0);
    const float positions[3][4] = {{-0.75f,-0.75f,0.2f,1}, {-0.75f,0.75f,0.6f,1}, {0.75f,-0.75f,0.9f,1}};
    const uint32_t normals[3] = {0xFFF80001u,0x7FC12345u,0x12345678u};
    const int16_t shorts[3][3] = {{-32768,16384,32767},{4095,-12345,23000},{-8192,32767,-1}};
    const uint8_t bytes[3][3] = {{0,127,255},{83,191,1},{247,35,164}};
    for (uint32_t vertex = 0; vertex < 3; vertex++) {
        uint8_t *p = raw.data() + size_t(vertex + 7) * stride;
        memcpy(p + 1, positions[vertex], 16); memcpy(p + 18, &normals[vertex], 4);
        memcpy(p + 23, shorts[vertex], 6); memcpy(p + 30, bytes[vertex], 3);
    }
    metal_vertex_declaration declaration{};
    declaration.element_count = 4; declaration.packed_mask = 2;
    declaration.elements[0] = {0,0,0x42,16,1}; declaration.elements[1] = {1,0,0x16,4,18};
    declaration.elements[2] = {2,0,0x31,6,23}; declaration.elements[3] = {3,0,0x34,3,30};
    metal_vertex_stream streams[16]{}; streams[0] = {raw.data(),raw.size(),stride};
    float fixed[16][4]{};
    for (auto &reg : fixed) reg[3] = 1;
    size_t compact_bytes = 0;
    require(metal_vertex_compact_size(&declaration,streams,plan.source_first,plan.source_count,&compact_bytes) == METAL_VERTEX_OK,
        "Original NV2A compact triangle sizing failed");
    std::vector<uint8_t> compact(compact_bytes), expanded(3 * 256);
    require(metal_vertex_compact_pack(&declaration,streams,fixed,plan.source_first,plan.source_count,
        compact.data(),compact.size()) == METAL_VERTEX_OK, "Original NV2A compact triangle packing failed");
    require(metal_vertex_fetch(&declaration,streams,fixed,plan.source_first,plan.source_count,
        expanded.data(),expanded.size()) == METAL_VERTEX_OK, "Original NV2A CPU triangle fetch failed");
    RenderUniforms uniforms{};
    for (uint32_t row = 0; row < 4; row++) uniforms.c[row][row] = 1;
    uniforms.c[4][2] = 2; uniforms.c[5][3] = 0.5f;
    const float scale[4] = {32,-32,1,0}, offset[4] = {32,32,0,0};
    memcpy(uniforms.c[58],scale,16); memcpy(uniforms.viewport_scale,scale,16);
    memcpy(uniforms.c[59],offset,16); memcpy(uniforms.viewport_offset,offset,16);
    uniforms.point_size = 1;
    NSError *error = nil;
    NSString *cpu = [NSString stringWithContentsOfFile:[folder stringByAppendingPathComponent:@"render/expanded.metal"]
        encoding:NSUTF8StringEncoding error:&error];
    NSString *gpu = [NSString stringWithContentsOfFile:[folder stringByAppendingPathComponent:@"render/compact.metal"]
        encoding:NSUTF8StringEncoding error:&error];
    require(cpu && gpu, "Original NV2A render sources missing");
    size_t compared = 0;
    for (MTLPixelFormat format : {MTLPixelFormatRGBA8Unorm,MTLPixelFormatBGRA8Unorm}) {
        auto reference = render(device,queue,options,cpu,false,format,expanded,indices,uniforms);
        auto actual = render(device,queue,options,gpu,true,format,compact,indices,uniforms);
        require(reference == actual, "Original NV2A compact color/depth render differs from CPU expansion");
        uint32_t covered = 0; bool varied = false; uint32_t first_color = 0;
        for (uint32_t pixel = 0; pixel < 4096; pixel++) {
            float depth; memcpy(&depth,actual.data() + 16384 + pixel * 4,4);
            if (depth < 1) {
                uint32_t color; memcpy(&color,actual.data() + pixel * 4,4);
                if (!covered) first_color = color;
                varied |= color != first_color; covered++;
            }
        }
        require(covered > 100 && varied, "Original NV2A parity fixture must rasterize varying nonempty color/depth");
        compared += actual.size();
    }
    return compared;
}
int main(int argc, char **argv) {
    @autoreleasepool {
        try {
            require(argc == 2, "Usage: metal_vertex_decode compact-shader-directory");
            auto device = MTLCreateSystemDefaultDevice(); require(device != nil, "Metal device required");
            auto queue = [device newCommandQueue]; require(queue != nil, "Metal queue required");
            auto options = [MTLCompileOptions new];
            options.preserveInvariance = YES;
            if (@available(macOS 15.0, *)) {
                options.mathMode = MTLMathModeFast;
                options.mathFloatingPointFunctions = MTLMathFloatingPointFunctionsFast;
            }
            NSString *source = [NSString stringWithFormat:@"#include <metal_stdlib>\nusing namespace metal;\n%s\n"
                "kernel void decode(device const uchar *input [[buffer(0)]], device float4 *output [[buffer(1)]],\n"
                "device uint *output_packed [[buffer(2)]], uint id [[thread_position_in_grid]]) {\n"
                "float4 values[16]; uint packed[16]; xgpu_vertex_fetch(input,id,values,packed);\n"
                "for(uint reg=0;reg<16;reg++){output[id*16+reg]=values[reg];output_packed[id*16+reg]=packed[reg];}}\n",
                xgpu_vertex_decode_msl];
            NSError *error = nil;
            auto library = [device newLibraryWithSource:source options:options error:&error];
            if (!library) fprintf(stderr, "%s\n", error.description.UTF8String);
            require(library != nil, "Production decoder compilation failed");
            auto pipeline = [device newComputePipelineStateWithFunction:[library newFunctionWithName:@"decode"] error:&error];
            require(pipeline != nil, "Production decoder pipeline failed");
            const uint32_t types[] = {0x02,0x12,0x22,0x32,0x42,0x72,0x40,0x16,
                0x11,0x21,0x31,0x41,0x15,0x25,0x35,0x45,0x14,0x24,0x34,0x44};
            size_t comparisons = 0;
            for (uint32_t type : types) {
                const uint32_t count = (type & 15) == 1 || (type & 15) == 5 ? 65536u : 256u;
                auto f = fixture(type, count); comparisons += compare(device, queue, pipeline, f);
            }
            for (uint32_t type : {0x32u,0x21u,0x16u}) {
                auto constant = fixture(type, 257, true); comparisons += compare(device, queue, pipeline, constant);
                auto missing = fixture(type, 257, false, true); comparisons += compare(device, queue, pipeline, missing);
            }
            auto mixed = mixed_fixture(); comparisons += compare(device, queue, pipeline, mixed);
            NSString *folder = [NSString stringWithUTF8String:argv[1]];
            NSArray<NSString *> *files = [NSFileManager.defaultManager contentsOfDirectoryAtPath:folder error:&error];
            size_t compiled = 0;
            for (NSString *file in files) if ([file.pathExtension isEqualToString:@"metal"]) {
                NSString *text = [NSString stringWithContentsOfFile:[folder stringByAppendingPathComponent:file]
                    encoding:NSUTF8StringEncoding error:&error];
                auto shader = [device newLibraryWithSource:text options:options error:&error];
                if (!shader) fprintf(stderr, "%s: %s\n", file.UTF8String, error.description.UTF8String);
                require(shader != nil, "Compact production shader compilation failed"); compiled++;
            }
            require(compiled == 134, "Expected both packed masks for all 67 original vertex programs");
            const size_t rendered = render_parity(device,queue,options,folder);
            printf("{\"formats\":20,\"signed_short_values\":65536,\"byte_values\":256,"
                "\"exact_register_comparisons\":%zu,\"compact_programs_compiled\":%zu,"
                "\"original_nv2a_render_equal_bytes\":%zu}\n", comparisons, compiled, rendered);
            return 0;
        } catch (const std::exception &error) {
            fprintf(stderr, "%s\n", error.what()); return 1;
        }
    }
}
