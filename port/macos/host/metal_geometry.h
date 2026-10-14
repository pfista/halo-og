/* A validated, immutable geometry snapshot. Only this factory can construct
 * the proof. Guest bytes are copied to owned staging, then execution uploads
 * private buffers before any dependent draw on the same ordered queue. */
#ifndef HALO_METAL_GEOMETRY_H
#define HALO_METAL_GEOMETRY_H
#import <Metal/Metal.h>
#include "metal_compact_vertex.h"
#include <memory>
#include <cstring>
#include <atomic>

class HaloMetalGeometry {
    id<MTLBuffer> vertices_, indices_;
    mutable id<MTLBuffer> staging_;
    mutable __weak id<MTLCommandBuffer> upload_command_;
    mutable id<MTLCommandQueue> upload_queue_ = nil;
    mutable std::atomic<bool> completed_{false};
    std::weak_ptr<const HaloMetalGeometry> self_;
    uint32_t vertex_count_, index_count_, packed_mask_, vertex_bytes_;
    HaloMetalGeometry(id<MTLBuffer> vertices, id<MTLBuffer> indices, id<MTLBuffer> staging,
        uint32_t vertex_count, uint32_t index_count, uint32_t packed_mask, uint32_t vertex_bytes)
        : vertices_(vertices), indices_(indices), staging_(staging), vertex_count_(vertex_count),
          index_count_(index_count), packed_mask_(packed_mask), vertex_bytes_(vertex_bytes) {}
public:
    static std::shared_ptr<const HaloMetalGeometry> create(id<MTLDevice> device,
        const void *vertices, uint32_t vertex_bytes, uint32_t vertex_count,
        const void *indices, uint32_t index_count, uint32_t packed_mask) {
        if (!device || !indices || !index_count ||
            vertex_bytes > 64u * 1024u * 1024u ||
            uint64_t(vertex_bytes) + uint64_t(index_count) * 4 > 64u * 1024u * 1024u || !vertices) return {};
        const NSUInteger index_bytes = NSUInteger(index_count) * 4;
        const NSUInteger index_offset = (NSUInteger(vertex_bytes) + 15) & ~NSUInteger(15);
        auto copy = [device newBufferWithLength:index_offset + index_bytes options:MTLResourceStorageModeShared];
        if (!copy) return {};
        memcpy(copy.contents,vertices,vertex_bytes);
        memset((uint8_t *)copy.contents + vertex_bytes,0,index_offset - vertex_bytes);
        memcpy((uint8_t *)copy.contents + index_offset,indices,index_bytes);
        // Validate the owned bytes that will reach the GPU. The source cannot
        // change after validation and before the copy to manufacture a proof.
        if (!halo_metal_compact_vertices_valid(copy.contents,vertex_bytes,vertex_count,packed_mask)) return {};
        for (uint32_t i = 0; i < index_count; i++) {
            uint32_t value; memcpy(&value,(uint8_t *)copy.contents + index_offset + size_t(i) * 4,4);
            if (value >= vertex_count) return {};
        }
        auto vertex_buffer = [device newBufferWithLength:(NSUInteger(vertex_bytes) + 3) & ~NSUInteger(3)
            options:MTLResourceStorageModePrivate];
        auto index_buffer = [device newBufferWithLength:index_bytes options:MTLResourceStorageModePrivate];
        if (!vertex_buffer || !index_buffer) return {};
        auto result = std::shared_ptr<HaloMetalGeometry>(new HaloMetalGeometry(
            vertex_buffer,index_buffer,copy,vertex_count,index_count,packed_mask,vertex_bytes));
        result->self_ = result;
        return result;
    }
    id<MTLBuffer> vertices() const { return vertices_; }
    id<MTLBuffer> indices() const { return indices_; }
    uint32_t vertexCount() const { return vertex_count_; }
    uint32_t indexCount() const { return index_count_; }
    uint32_t packedMask() const { return packed_mask_; }
    uint32_t vertexBytes() const { return vertex_bytes_; }
    size_t bytes() const { return size_t(vertex_bytes_) + size_t(index_count_) * 4; }
    bool matches(id<MTLDevice> device, id<MTLBuffer> vertices, NSUInteger vertex_offset,
        NSUInteger vertex_bytes, NSUInteger vertex_count, id<MTLBuffer> indices,
        NSUInteger index_offset, NSUInteger index_count, uint32_t packed_mask) const {
        return vertices == vertices_ && indices == indices_ && !vertex_offset && !index_offset &&
            vertices_.device == device && indices_.device == device &&
            vertices_.storageMode == MTLStorageModePrivate && indices_.storageMode == MTLStorageModePrivate &&
            vertex_bytes == vertex_bytes_ && vertex_count == vertex_count_ &&
            index_count == index_count_ && packed_mask == packed_mask_;
    }
    bool upload(id<MTLCommandBuffer> command) const {
        auto staging = staging_;
        const NSUInteger index_offset = (NSUInteger(vertex_bytes_) + 15) & ~NSUInteger(15);
        if (!command || command.status != MTLCommandBufferStatusNotEnqueued ||
            command.commandQueue.device != vertices_.device ||
            !staging || staging.device != vertices_.device ||
            staging.length < index_offset + NSUInteger(index_count_) * 4) return false;
        auto encoder = [command blitCommandEncoder]; if (!encoder) return false;
        [encoder copyFromBuffer:staging sourceOffset:0 toBuffer:vertices_ destinationOffset:0 size:vertices_.length];
        [encoder copyFromBuffer:staging sourceOffset:index_offset toBuffer:indices_ destinationOffset:0 size:NSUInteger(index_count_) * 4];
        [encoder endEncoding];
        upload_command_ = command; upload_queue_ = command.commandQueue;
        auto weak = self_;
        [command addCompletedHandler:^(id<MTLCommandBuffer> buffer) {
            if (buffer.status == MTLCommandBufferStatusCompleted) {
                auto input = weak.lock();
                if (input) input->completed_.store(true,std::memory_order_release);
            }
        }];
        staging_ = nil; return true;
    }
    // Retirement must publish readiness before dropping the submission's last
    // strong command reference. Observing Completed does not imply our queued
    // completion callback has already stored the flag.
    bool retireUpload(id<MTLCommandBuffer> command) const {
        auto upload = upload_command_;
        if (!command || command != upload || command.commandQueue != upload_queue_ ||
            command.status != MTLCommandBufferStatusCompleted) return false;
        completed_.store(true,std::memory_order_release); return true;
    }
    bool readyForDraw(id<MTLCommandBuffer> command) const {
        if (!command || command.commandQueue != upload_queue_) return false;
        if (completed_.load(std::memory_order_acquire)) return true;
        auto upload = upload_command_;
        return upload && (upload == command ||
            upload.status == MTLCommandBufferStatusCommitted ||
            upload.status == MTLCommandBufferStatusScheduled ||
            upload.status == MTLCommandBufferStatusCompleted);
    }
};
#endif
