/* Packet-only draw preparation. This interface is internal to the native
 * transport; mutable direct draw callers use metal_draw_encoder.h instead. */
#ifndef HALO_METAL_DRAW_ENCODER_INTERNAL_H
#define HALO_METAL_DRAW_ENCODER_INTERNAL_H
#import "metal_draw_encoder.h"

/* Created only by the encoder after complete draw and binding validation.
 * The token strongly owns its draw snapshot, resources, pipeline/depth state
 * and originating encoder. Snapshot fields cannot be changed after creation.
 * Buffer contents still belong to the packet: callers must keep those bytes
 * immutable until every consuming command buffer has completed. */
@interface HaloMetalPreparedDraw : NSObject
- (instancetype)init NS_UNAVAILABLE;
+ (instancetype)new NS_UNAVAILABLE;
- (const HaloMetalDraw &)draw;
@end

@interface HaloMetalDrawEncoder (PacketPreparation)
- (HaloMetalPreparedDraw *)preparePacketDraw:(const HaloMetalDraw &)draw
                           usedTextureMask:(uint32_t *)mask error:(NSError **)error;
/* Uses the retained preparation, while checking current command-buffer and
 * geometry-upload ordering. A token is valid only on its originating encoder.
 * initialPass is optional and starts a fresh pass even when reuse is possible.
 * It must contain the exact draw attachments at level/slice/depthPlane zero,
 * Load/Clear with Store, the complete target footprint, and no query, resolve
 * or additional color attachments. Only a trusted, validated packet clear may
 * supply it. All other pass boundaries follow the public reuse contract. */
- (BOOL)encodePreparedPacketDraw:(HaloMetalPreparedDraw *)prepared
                   commandBuffer:(id<MTLCommandBuffer>)commandBuffer
                       reusePass:(BOOL)reusePass
                     initialPass:(MTLRenderPassDescriptor *)initialPass error:(NSError **)error;
@end
#endif
