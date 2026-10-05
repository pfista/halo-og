#include <metal_stdlib>
using namespace metal;

// The exported vertex buffer is shared with the BSP's 28-byte vertices.
struct SkyVertex { packed_float3 position; packed_float2 uv; packed_float2 lightmapUV; };
struct SkyFrameUniforms {
    float4x4 viewProjection;
    float4 cameraPositionExposure;
    float4 planarFog;
};
struct SkyMaterialUniforms {
    uint kind;
    uint padding[3];
    float4 scale01;
    float4 scale2;
    float4 offset01;
    float4 offset2;
};
struct SkyVaryings { float4 position [[position]]; float2 uv; };

float3 sky_world_position(float3 modelPosition, float3 cameraPosition) {
    // render_sky.c:219-233 scales the node matrix and partially follows the
    // camera. Retain its small camera parallax rather than pinning the dome.
    return modelPosition * (1.0 / 1024.0) + cameraPosition * (1023.0 / 1024.0);
}

float4 sky_combine(float4 t0, float4 t1, float4 t2, uint kind) {
    // Generic planet/ring maps have no stages: their original combiner copies
    // texture zero. Chicago starts at t0, then applies each earlier map's
    // function to the following texture (chicago_preprocessor.c:154-187).
    if (kind == 1) return clamp(t0, 0.0, 1.0);
    if (kind == 2) return clamp(t0 * t1, 0.0, 1.0);
    float3 stars = clamp(t0.rgb * t1.rgb, -1.0, 1.0);
    return float4(clamp(max(stars, 0.0) + t2.rgb, 0.0, 1.0), clamp(t0.a, 0.0, 1.0));
}

float4 sky_apply_planar_fog(float4 color, float4 fogColorDensity) {
    // Original sky alpha-blend draws use camera-dependent planar fog, without
    // changing the planet/cloud alpha (transparent_geometry.c:2059,2572).
    color.rgb = mix(color.rgb, fogColorDensity.rgb, clamp(fogColorDensity.a, 0.0, 1.0));
    return color;
}

vertex SkyVaryings sky_vertex(uint index [[vertex_id]],
                            const device SkyVertex *vertices [[buffer(0)]],
                            constant SkyFrameUniforms &frame [[buffer(1)]]) {
    SkyVertex v = vertices[index];
    float3 world = sky_world_position(float3(v.position), frame.cameraPositionExposure.xyz);
    return { frame.viewProjection * float4(world, 1.0), float2(v.uv) };
}

struct SkyFragmentOutput { float4 color [[color(0)]]; uint sampleMask [[sample_mask]]; };

fragment SkyFragmentOutput sky_fragment(SkyVaryings in [[stage_in]],
                            texture2d<float> texture0 [[texture(0)]],
                            texture2d<float> texture1 [[texture(1)]],
                            texture2d<float> texture2 [[texture(2)]],
                            constant SkyFrameUniforms &frame [[buffer(0)]],
                            constant SkyMaterialUniforms &material [[buffer(1)]]) {
    // The loader accepts only the three verified Blood Gulch configurations.
    if (material.kind < 1 || material.kind > 3) discard_fragment();
    constexpr sampler repeating(filter::linear, mip_filter::linear, address::repeat);
    float4 t0 = texture0.sample(repeating, in.uv * material.scale01.xy + material.offset01.xy);
    float4 t1 = texture1.sample(repeating, in.uv * material.scale01.zw + material.offset01.zw);
    float4 t2 = texture2.sample(repeating, in.uv * material.scale2.xy + material.offset2.xy);
    float4 color = sky_apply_planar_fog(sky_combine(t0, t1, t2, material.kind), frame.planarFog);
    color.rgb *= frame.cameraPositionExposure.w;
    return {color, 0xffffffffu};
}
