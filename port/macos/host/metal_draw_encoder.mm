#import "metal_draw_encoder.h"
#include <cmath>
#include <cstdint>
#include <cstring>

NSString *const HaloMetalDrawErrorDomain = @"HaloMetalDraw";

namespace {
BOOL fail(NSError **error, HaloMetalDrawError code, NSString *message) {
    if (error) *error = [NSError errorWithDomain:HaloMetalDrawErrorDomain code:code
        userInfo:@{NSLocalizedDescriptionKey: message}];
    return NO;
}
MTLCompareFunction compare(uint32_t value) {
    static const MTLCompareFunction values[] = {MTLCompareFunctionNever,
        MTLCompareFunctionNever, MTLCompareFunctionLess, MTLCompareFunctionEqual,
        MTLCompareFunctionLessEqual, MTLCompareFunctionGreater, MTLCompareFunctionNotEqual,
        MTLCompareFunctionGreaterEqual, MTLCompareFunctionAlways};
    return values[value];
}
MTLStencilOperation stencil(uint32_t value) {
    static const MTLStencilOperation values[] = {MTLStencilOperationKeep,
        MTLStencilOperationKeep, MTLStencilOperationZero, MTLStencilOperationReplace,
        MTLStencilOperationIncrementClamp, MTLStencilOperationDecrementClamp,
        MTLStencilOperationInvert, MTLStencilOperationIncrementWrap, MTLStencilOperationDecrementWrap};
    return values[value];
}
MTLBlendFactor blend(uint32_t value) {
    static const MTLBlendFactor values[] = {MTLBlendFactorZero, MTLBlendFactorZero,
        MTLBlendFactorOne, MTLBlendFactorSourceColor, MTLBlendFactorOneMinusSourceColor,
        MTLBlendFactorSourceAlpha, MTLBlendFactorOneMinusSourceAlpha, MTLBlendFactorDestinationAlpha,
        MTLBlendFactorOneMinusDestinationAlpha, MTLBlendFactorDestinationColor,
        MTLBlendFactorOneMinusDestinationColor, MTLBlendFactorSourceAlphaSaturated,
        MTLBlendFactorBlendColor, MTLBlendFactorOneMinusBlendColor,
        MTLBlendFactorBlendAlpha, MTLBlendFactorOneMinusBlendAlpha};
    return values[value];
}
MTLBlendOperation blendOperation(uint32_t value) {
    static const MTLBlendOperation values[] = {MTLBlendOperationAdd, MTLBlendOperationAdd,
        MTLBlendOperationSubtract, MTLBlendOperationReverseSubtract, MTLBlendOperationMin, MTLBlendOperationMax};
    return values[value];
}
MTLColorWriteMask writeMask(uint32_t value) {
    return (MTLColorWriteMask)(((value & 1) ? MTLColorWriteMaskRed : 0) |
        ((value & 2) ? MTLColorWriteMaskGreen : 0) | ((value & 4) ? MTLColorWriteMaskBlue : 0) |
        ((value & 8) ? MTLColorWriteMaskAlpha : 0));
}
bool range(id<MTLBuffer> buffer, NSUInteger offset, NSUInteger count,
           NSUInteger stride, NSUInteger alignment, id<MTLDevice> device) {
    return buffer && buffer.device == device && offset % alignment == 0 &&
        offset <= buffer.length && count <= (buffer.length - offset) / stride;
}
bool finite(const float *values, size_t count) {
    for (size_t i = 0; i < count; i++) if (!std::isfinite(values[i])) return false;
    return true;
}
struct PipelineKey {
    uintptr_t vertex, fragment;
    uint64_t color, depth;
    uint32_t packed, mask, blendEnabled, source, destination, operation;
};
struct DepthKey {
    uint32_t enabled, write, compare, stencilEnabled, stencilCompare, readMask,
        writeMask, fail, depthFail, pass;
};
}

@interface HaloMetalPipelineEntry : NSObject
@property(nonatomic, strong) id<MTLRenderPipelineState> pipeline;
@property(nonatomic, strong) MTLRenderPipelineReflection *reflection;
@property(nonatomic, strong) id<MTLFunction> vertex, fragment;
@end
@implementation HaloMetalPipelineEntry
@end

@implementation HaloMetalDrawEncoder {
    id<MTLDevice> _device;
    NSMutableDictionary<NSData *, HaloMetalPipelineEntry *> *_pipelines;
    NSMutableDictionary<NSData *, id<MTLDepthStencilState>> *_depthStates;
}
- (instancetype)initWithDevice:(id<MTLDevice>)device {
    if (!device) return nil;
    if ((self = [super init])) {
        _device = device; _pipelines = [NSMutableDictionary new];
        _depthStates = [NSMutableDictionary new];
    }
    return self;
}
- (void)clearCaches { @synchronized(self) { [_pipelines removeAllObjects]; [_depthStates removeAllObjects]; } }
- (void)removePipelinesForVertexFunction:(id<MTLFunction>)vertex fragmentFunction:(id<MTLFunction>)fragment {
    @synchronized(self) {
        for (NSData *key in [_pipelines.allKeys copy]) {
            HaloMetalPipelineEntry *entry = _pipelines[key];
            if ((vertex && entry.vertex == vertex) || (fragment && entry.fragment == fragment))
                [_pipelines removeObjectForKey:key];
        }
    }
}
- (BOOL)validateDraw:(const HaloMetalDraw &)draw error:(NSError **)error {
    const halo_metal_draw_state &s = draw.state;
    if (!draw.visibilityBuffer) {
        if (draw.visibilityOffset || draw.visibilityMode != MTLVisibilityResultModeDisabled)
            return fail(error, HaloMetalDrawInvalid, @"Inactive query must not supply a visibility offset or mode");
    } else if ((draw.visibilityMode != MTLVisibilityResultModeBoolean &&
                draw.visibilityMode != MTLVisibilityResultModeCounting) ||
               draw.visibilityBuffer.storageMode != MTLStorageModeShared ||
               !range(draw.visibilityBuffer, draw.visibilityOffset, 1, sizeof(uint64_t), sizeof(uint64_t), _device)) {
        return fail(error, HaloMetalDrawInvalid, @"Active query requires Boolean/Counting and an aligned shared 8-byte result word on the encoder device");
    }
    if (!draw.vertexFunction || !draw.fragmentFunction || draw.vertexFunction.device != _device ||
        draw.fragmentFunction.device != _device || draw.vertexFunction.functionType != MTLFunctionTypeVertex ||
        draw.fragmentFunction.functionType != MTLFunctionTypeFragment)
        return fail(error, HaloMetalDrawInvalid, @"Draw requires vertex and fragment functions on the encoder device");
    if (!draw.color && !draw.depthStencil)
        return fail(error, HaloMetalDrawInvalid, @"Draw has no original attachment");
    id<MTLTexture> target = draw.color ?: draw.depthStencil;
    for (id<MTLTexture> texture in @[draw.color ?: (id)NSNull.null, draw.depthStencil ?: (id)NSNull.null]) {
        if ((id)texture == NSNull.null) continue;
        if (texture.device != _device || texture.textureType != MTLTextureType2D || texture.sampleCount != 1 ||
            !(texture.usage & MTLTextureUsageRenderTarget) || texture.width < target.width || texture.height < target.height)
            return fail(error, HaloMetalDrawUnsupported, @"Original attachments must be single-sample 2D targets covering the color footprint");
    }
    if (draw.color && draw.color.pixelFormat != MTLPixelFormatRGBA8Unorm && draw.color.pixelFormat != MTLPixelFormatBGRA8Unorm)
        return fail(error, HaloMetalDrawUnsupported, @"Unsupported original color attachment format");
    if (draw.depthStencil && draw.depthStencil.pixelFormat != MTLPixelFormatDepth32Float_Stencil8)
        return fail(error, HaloMetalDrawUnsupported, @"Unsupported original native depth/stencil attachment format");
    if (s.color_write_mask > 15 || s.blend_enabled > 1 || s.blend_source < 1 || s.blend_source > 15 ||
        s.blend_destination < 1 || s.blend_destination > 15 || s.blend_operation < 1 || s.blend_operation > 5 ||
        s.depth_enabled > 1 || s.depth_write > 1 || s.depth_compare < 1 || s.depth_compare > 8 ||
        s.stencil_enabled > 1 || s.stencil_compare < 1 || s.stencil_compare > 8 ||
        s.stencil_fail < 1 || s.stencil_fail > 8 || s.stencil_depth_fail < 1 || s.stencil_depth_fail > 8 ||
        s.stencil_pass < 1 || s.stencil_pass > 8 || s.front_winding > 1 || s.cull_mode > 2 ||
        s.depth_clip_mode > 1 || s.fill_mode > 1 || s.reserved_float != 0 || !finite(s.viewport, 6) ||
        !finite(s.blend_color, 4) || !std::isfinite(s.depth_bias) || !std::isfinite(s.slope_depth_bias) ||
        !std::isfinite(s.depth_bias_clamp))
        return fail(error, HaloMetalDrawInvalid, @"Invalid or unsupported numeric original draw state");
    if ((!draw.color && (s.color_write_mask || s.blend_enabled)) ||
        (!draw.depthStencil && (s.depth_enabled || s.stencil_enabled)))
        return fail(error, HaloMetalDrawInvalid, @"Enabled original write/test has no matching attachment");
    if (s.viewport[2] <= 0 || s.viewport[3] <= 0 || s.viewport[4] < 0 ||
        s.viewport[5] > 1 || s.viewport[4] > s.viewport[5] ||
        !s.scissor[2] || !s.scissor[3] || s.scissor[0] > target.width || s.scissor[1] > target.height ||
        s.scissor[2] > target.width - s.scissor[0] || s.scissor[3] > target.height - s.scissor[1])
        return fail(error, HaloMetalDrawInvalid, @"Original viewport/depth range/scissor exceeds the target contract");
    for (unsigned i = 0; i < 4; i++) if (s.blend_color[i] < 0 || s.blend_color[i] > 1)
        return fail(error, HaloMetalDrawInvalid, @"Original blend color lies outside 0..1");
    if (!draw.vertexCount || !draw.indexCount || draw.packedMask > UINT16_MAX ||
        draw.primitive > MTLPrimitiveTypeTriangleStrip ||
        (draw.primitive == MTLPrimitiveTypeLine && draw.indexCount % 2) ||
        (draw.primitive == MTLPrimitiveTypeTriangle && draw.indexCount % 3) ||
        (draw.primitive == MTLPrimitiveTypeLineStrip && draw.indexCount < 2) ||
        (draw.primitive == MTLPrimitiveTypeTriangleStrip && draw.indexCount < 3))
        return fail(error, HaloMetalDrawInvalid, @"Invalid expanded original geometry/topology");
    if (!range(draw.vertices, draw.vertexOffset, draw.vertexCount, HaloMetalVertexStride, 16, _device) ||
        !range(draw.indices, draw.indexOffset, draw.indexCount, 4, 4, _device) ||
        !range(draw.vertexUniforms, draw.vertexUniformOffset, 1, HaloMetalVertexUniformSize, 16, _device) ||
        !range(draw.pixelUniforms, draw.pixelUniformOffset, 1, HaloMetalPixelUniformSize, 16, _device))
        return fail(error, HaloMetalDrawInvalid, @"Original input/uniform buffer range, alignment or device is invalid");
    if (draw.indices.storageMode != MTLStorageModePrivate) {
        const uint8_t *bytes = (const uint8_t *)draw.indices.contents + draw.indexOffset;
        for (NSUInteger i = 0; i < draw.indexCount; i++) {
            uint32_t index; memcpy(&index, bytes + i * 4, 4);
            if (index >= draw.vertexCount)
                return fail(error, HaloMetalDrawInvalid, @"Expanded original index exceeds its vertex range");
        }
    }
    return YES;
}
- (HaloMetalPipelineEntry *)pipelineForDraw:(const HaloMetalDraw &)draw error:(NSError **)error {
    const halo_metal_draw_state &s = draw.state;
    PipelineKey key = {};
    key.vertex = (uintptr_t)(__bridge void *)draw.vertexFunction;
    key.fragment = (uintptr_t)(__bridge void *)draw.fragmentFunction;
    key.color = draw.color ? draw.color.pixelFormat : MTLPixelFormatInvalid;
    key.depth = draw.depthStencil ? draw.depthStencil.pixelFormat : MTLPixelFormatInvalid;
    key.packed = draw.packedMask; key.mask = s.color_write_mask; key.blendEnabled = s.blend_enabled;
    key.source = s.blend_source; key.destination = s.blend_destination; key.operation = s.blend_operation;
    NSData *bytes = [NSData dataWithBytes:&key length:sizeof(key)];
    HaloMetalPipelineEntry *entry = _pipelines[bytes];
    if (entry) return entry;
    MTLRenderPipelineDescriptor *description = [MTLRenderPipelineDescriptor new];
    description.vertexFunction = draw.vertexFunction; description.fragmentFunction = draw.fragmentFunction;
    description.depthAttachmentPixelFormat = description.stencilAttachmentPixelFormat = (MTLPixelFormat)key.depth;
    // NV2A emits point size for triangle programs as well. The draw specifies
    // topology; declaring triangles here would reject that original output.
    description.inputPrimitiveTopology = MTLPrimitiveTopologyClassUnspecified;
    MTLVertexDescriptor *layout = [MTLVertexDescriptor vertexDescriptor];
    for (unsigned reg = 0; reg < 16; reg++) {
        layout.attributes[reg].format = (draw.packedMask & (1u << reg)) ? MTLVertexFormatUInt : MTLVertexFormatFloat4;
        layout.attributes[reg].offset = reg * 16; layout.attributes[reg].bufferIndex = 1;
    }
    layout.layouts[1].stride = HaloMetalVertexStride; description.vertexDescriptor = layout;
    MTLRenderPipelineColorAttachmentDescriptor *color = description.colorAttachments[0];
    color.pixelFormat = (MTLPixelFormat)key.color; color.writeMask = writeMask(s.color_write_mask);
    color.blendingEnabled = s.blend_enabled;
    color.sourceRGBBlendFactor = color.sourceAlphaBlendFactor = blend(s.blend_source);
    color.destinationRGBBlendFactor = color.destinationAlphaBlendFactor = blend(s.blend_destination);
    color.rgbBlendOperation = color.alphaBlendOperation = blendOperation(s.blend_operation);
    MTLRenderPipelineReflection *reflection = nil;
    NSError *underlying = nil;
    id<MTLRenderPipelineState> pipeline = [_device newRenderPipelineStateWithDescriptor:description
        options:MTLPipelineOptionBindingInfo reflection:&reflection error:&underlying];
    if (!pipeline || !reflection) {
        fail(error, HaloMetalDrawPipelineFailure, underlying.localizedDescription ?: @"Original draw pipeline/reflection creation failed");
        return nil;
    }
    entry = [HaloMetalPipelineEntry new]; entry.pipeline = pipeline; entry.reflection = reflection;
    entry.vertex = draw.vertexFunction; entry.fragment = draw.fragmentFunction; _pipelines[bytes] = entry;
    return entry;
}
- (id<MTLDepthStencilState>)depthForDraw:(const HaloMetalDraw &)draw error:(NSError **)error {
    const halo_metal_draw_state &s = draw.state;
    DepthKey key = {s.depth_enabled, s.depth_write, s.depth_compare, s.stencil_enabled,
        s.stencil_compare, s.stencil_read_mask, s.stencil_write_mask, s.stencil_fail, s.stencil_depth_fail, s.stencil_pass};
    NSData *bytes = [NSData dataWithBytes:&key length:sizeof(key)];
    id<MTLDepthStencilState> result = _depthStates[bytes]; if (result) return result;
    MTLDepthStencilDescriptor *description = [MTLDepthStencilDescriptor new];
    description.depthCompareFunction = s.depth_enabled ? compare(s.depth_compare) : MTLCompareFunctionAlways;
    description.depthWriteEnabled = s.depth_enabled && s.depth_write;
    if (s.stencil_enabled) {
        MTLStencilDescriptor *face = [MTLStencilDescriptor new];
        face.stencilCompareFunction = compare(s.stencil_compare);
        face.readMask = s.stencil_read_mask; face.writeMask = s.stencil_write_mask;
        face.stencilFailureOperation = stencil(s.stencil_fail);
        face.depthFailureOperation = stencil(s.stencil_depth_fail); face.depthStencilPassOperation = stencil(s.stencil_pass);
        description.frontFaceStencil = face; description.backFaceStencil = face;
    }
    result = [_device newDepthStencilStateWithDescriptor:description];
    if (!result) fail(error, HaloMetalDrawPipelineFailure, @"Original depth/stencil state creation failed");
    else _depthStates[bytes] = result;
    return result;
}
- (BOOL)validateBindings:(MTLRenderPipelineReflection *)reflection draw:(const HaloMetalDraw &)draw error:(NSError **)error {
    uint32_t usedAuxiliarySamplers = 0;
    if (draw.alphaBorderMask > 15 || draw.volumeBorderMask > 15 ||
        (draw.alphaBorderMask & draw.volumeBorderMask))
        return fail(error, HaloMetalDrawInvalid, @"Unknown or conflicting border stage masks");
    const uint32_t auxiliaryMask = draw.alphaBorderMask | draw.volumeBorderMask;
    for (unsigned i = 0; i < 4; i++) {
        if (!!draw.samplers[4+i] != !!(auxiliaryMask & (1u << i)))
            return fail(error, HaloMetalDrawInvalid, @"Border companion does not match stage mask");
        if (auxiliaryMask & (1u << i)) {
            const MTLTextureType type = (draw.volumeBorderMask & (1u << i)) ? MTLTextureType3D : MTLTextureType2D;
            if (!draw.textures[i] || draw.textures[i].textureType != type || draw.textures[i].mipmapLevelCount <= 1)
                return fail(error, HaloMetalDrawInvalid, @"Border companion texture does not match typed stage contract");
        }
    }
    for (unsigned stage = 0; stage < 2; stage++) {
        NSArray<id<MTLBinding>> *bindings = stage ? reflection.fragmentBindings : reflection.vertexBindings;
        for (id<MTLBinding> binding in bindings) {
            if (!binding.used) continue;
            if (binding.type == MTLBindingTypeBuffer) {
                if (binding.index > (stage ? 0u : 1u))
                    return fail(error, HaloMetalDrawUnsupported, @"Shader requires an unsupported original buffer binding");
                NSUInteger available = binding.index == 1 ? HaloMetalVertexStride :
                    (stage ? HaloMetalPixelUniformSize : HaloMetalVertexUniformSize);
                if (((id<MTLBufferBinding>)binding).bufferDataSize > available)
                    return fail(error, HaloMetalDrawInvalid, @"Shader uniform/input structure exceeds the captured original buffer");
            } else if (binding.type == MTLBindingTypeTexture) {
                if (!stage || binding.index >= 4)
                    return fail(error, HaloMetalDrawUnsupported, @"Shader requires an unsupported original texture binding");
                id<MTLTexture> texture = draw.textures[binding.index];
                MTLTextureType type = ((id<MTLTextureBinding>)binding).textureType;
                if (!texture || texture.device != _device || texture.textureType != type ||
                    (type != MTLTextureType2D && type != MTLTextureTypeCube && type != MTLTextureType3D) ||
                    texture.sampleCount != 1 || !(texture.usage & MTLTextureUsageShaderRead) ||
                    texture == draw.color || texture == draw.depthStencil)
                    return fail(error, HaloMetalDrawInvalid, @"Used original texture is absent, mismatched or aliases a draw attachment");
            } else if (binding.type == MTLBindingTypeSampler) {
                if (!stage || binding.index >= 8 || !draw.samplers[binding.index] ||
                    draw.samplers[binding.index].device != _device)
                    return fail(error, HaloMetalDrawInvalid, @"Used original sampler is absent or mismatched");
                if (binding.index >= 4) usedAuxiliarySamplers |= 1u << (binding.index - 4);
            } else return fail(error, HaloMetalDrawUnsupported, @"Shader requires an unsupported original resource binding");
        }
    }
    if (usedAuxiliarySamplers != auxiliaryMask)
        return fail(error, HaloMetalDrawInvalid, @"Shader border companions do not match draw contract");
    return YES;
}
- (BOOL)prepareDraw:(const HaloMetalDraw &)draw error:(NSError **)error {
    @synchronized(self) {
        if (error) *error = nil;
        if (![self validateDraw:draw error:error]) return NO;
        HaloMetalPipelineEntry *entry = [self pipelineForDraw:draw error:error];
        return entry && [self validateBindings:entry.reflection draw:draw error:error] && [self depthForDraw:draw error:error];
    }
}
- (BOOL)usedTextureMaskForDraw:(const HaloMetalDraw &)draw mask:(uint32_t *)mask error:(NSError **)error {
    @synchronized(self) {
        if (!mask || ![self prepareDraw:draw error:error]) return NO;
        *mask = 0;
        for (id<MTLBinding> binding in [self pipelineForDraw:draw error:error].reflection.fragmentBindings)
            if (binding.used && binding.type == MTLBindingTypeTexture) *mask |= 1u << binding.index;
        return YES;
    }
}
- (BOOL)encodeDraw:(const HaloMetalDraw &)draw commandBuffer:(id<MTLCommandBuffer>)command error:(NSError **)error {
    @synchronized(self) {
        if (error) *error = nil;
        if (!command || command.commandQueue.device != _device || command.status != MTLCommandBufferStatusNotEnqueued)
            return fail(error, HaloMetalDrawInvalid, @"Draw requires an unsubmitted command buffer on the encoder device");
        if (![self prepareDraw:draw error:error]) return NO;
        HaloMetalPipelineEntry *entry = [self pipelineForDraw:draw error:error];
        id<MTLDepthStencilState> depth = [self depthForDraw:draw error:error];
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        id<MTLTexture> target = draw.color ?: draw.depthStencil;
        pass.renderTargetWidth = target.width; pass.renderTargetHeight = target.height;
        if (draw.color) {
            pass.colorAttachments[0].texture = draw.color;
            pass.colorAttachments[0].loadAction = MTLLoadActionLoad; pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        }
        if (draw.depthStencil) {
            pass.depthAttachment.texture = pass.stencilAttachment.texture = draw.depthStencil;
            pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionLoad;
            pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
        }
        // Default Reset semantics: the caller supplies a fresh word per draw.
        // No visibility buffer is attached to a pass outside an active query.
        if (draw.visibilityBuffer) pass.visibilityResultBuffer = draw.visibilityBuffer;
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        if (!encoder) return fail(error, HaloMetalDrawEncoderFailure, @"Original draw render encoder creation failed");
        const halo_metal_draw_state &s = draw.state;
        [encoder setRenderPipelineState:entry.pipeline]; [encoder setDepthStencilState:depth];
        [encoder setViewport:MTLViewport{s.viewport[0], s.viewport[1], s.viewport[2], s.viewport[3], s.viewport[4], s.viewport[5]}];
        [encoder setScissorRect:MTLScissorRect{s.scissor[0], s.scissor[1], s.scissor[2], s.scissor[3]}];
        [encoder setFrontFacingWinding:s.front_winding ? MTLWindingCounterClockwise : MTLWindingClockwise];
        [encoder setCullMode:(MTLCullMode)s.cull_mode];
        [encoder setDepthClipMode:s.depth_clip_mode ? MTLDepthClipModeClamp : MTLDepthClipModeClip];
        [encoder setTriangleFillMode:s.fill_mode ? MTLTriangleFillModeLines : MTLTriangleFillModeFill];
        [encoder setDepthBias:s.depth_bias slopeScale:s.slope_depth_bias clamp:s.depth_bias_clamp];
        [encoder setStencilReferenceValue:s.stencil_reference];
        [encoder setBlendColorRed:s.blend_color[0] green:s.blend_color[1] blue:s.blend_color[2] alpha:s.blend_color[3]];
        [encoder setVertexBuffer:draw.vertices offset:draw.vertexOffset atIndex:1];
        [encoder setVertexBuffer:draw.vertexUniforms offset:draw.vertexUniformOffset atIndex:0];
        [encoder setFragmentBuffer:draw.pixelUniforms offset:draw.pixelUniformOffset atIndex:0];
        for (unsigned i = 0; i < 4; i++) {
            [encoder setFragmentTexture:draw.textures[i] atIndex:i];
            [encoder setFragmentSamplerState:draw.samplers[i] atIndex:i];
            [encoder setFragmentSamplerState:draw.samplers[4+i] atIndex:4+i];
        }
        if (draw.visibilityBuffer)
            [encoder setVisibilityResultMode:draw.visibilityMode offset:draw.visibilityOffset];
        [encoder drawIndexedPrimitives:draw.primitive indexCount:draw.indexCount indexType:MTLIndexTypeUInt32
            indexBuffer:draw.indices indexBufferOffset:draw.indexOffset];
        [encoder endEncoding]; return YES;
    }
}
@end
