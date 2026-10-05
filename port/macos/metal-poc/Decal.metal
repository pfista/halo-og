#include <metal_stdlib>
#include "Fog.metal"
using namespace metal;

// Same <7f> preview vertex ABI and camera ABI as Scene.metal.
struct DecalVertex { packed_float3 position; packed_float2 uv; packed_float2 lightmapUV; };
struct DecalUniforms { float4x4 viewProjection; uint mode; float exposure; float2 pad; };
struct DecalVaryings {
    float4 position [[position]];
    float2 uv;
    float fogCoordinate;
};

vertex DecalVaryings decal_vertex(uint index [[vertex_id]],
                                 const device DecalVertex *vertices [[buffer(0)]],
                                 constant DecalUniforms &uniforms [[buffer(1)]],
                                 constant AtmosphericFogUniforms &fog [[buffer(2)]]) {
    DecalVertex v = vertices[index];
    float3 worldPosition = float3(v.position);
    return {uniforms.viewProjection * float4(worldPosition, 1), float2(v.uv),
            atmospheric_fog_coordinate(worldPosition, fog)};
}

struct DecalFragmentOutput { float4 color [[color(0)]]; uint sampleMask [[sample_mask]]; };

fragment DecalFragmentOutput decal_fragment(DecalVaryings in [[stage_in]],
                               texture2d<float> decal [[texture(0)]],
                               texture2d<float> densityLookup [[texture(1)]],
                               constant float4 &tintIntensity [[buffer(1)]],
                               constant AtmosphericFogUniforms &fog [[buffer(2)]]) {
    constexpr sampler clamped(filter::linear, mip_filter::linear,
                              address::clamp_to_edge);
    // rasterizer_xbox_decals.c ADD combiner: textureRGB * packed tintRGB *
    // (1-v9.a). Bitmap alpha is not an opacity mask for this original pass.
    float3 contribution = clamp(decal.sample(clamped, in.uv).rgb * tintIntensity.rgb,
                                0.0, 1.0) * tintIntensity.a;
    // Original primary decals precede atmospheric fog. The preview composes
    // opaque fog in Scene.metal, so only attenuate this additive contribution;
    // adding fog color here would fog the framebuffer twice.
    float fogAmount = atmospheric_fog_amount(in.fogCoordinate, densityLookup, fog);
    return {float4(contribution * (1.0 - fogAmount), 0), 0xffffffffu};
}

// Host pass: RGB ONE + ONE, alpha write disabled, LEQUAL, no depth write,
// original offset-equivalent bias (-8 constant, -2 slope). Exported positions
// also retain effects/decals.c's original 1/256 surface/normal offsets.
