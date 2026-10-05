#ifndef HALO_POC_ATMOSPHERIC_FOG
#define HALO_POC_ATMOSPHERIC_FOG
#include <metal_stdlib>
using namespace metal;

// Original c[-88]: camera.forward / (end-start), with
// w = -(start + dot(camera.position, camera.forward)) / (end-start).
// RGB and maximum density are the original packed 8-bit pixel constants.
struct AtmosphericFogUniforms {
    float4 coordinatePlane;
    float4 colorDensity;
};

float atmospheric_fog_coordinate(float3 worldPosition,
                                 constant AtmosphericFogUniforms &fog) {
    return dot(float4(worldPosition, 1.0), fog.coordinatePlane);
}

float atmospheric_fog_amount(float coordinate, texture2d<float> densityLookup,
                             constant AtmosphericFogUniforms &fog) {
    // rasterizer_xbox_environment_fog.c:620-628 and vertex shader6 T0.x.
    // The authored 16x16 AY8 lookup is a horizontal ramp. Preserve its
    // normalized-sampling half-texel endpoints rather than replacing it
    // with a linear distance approximation.
    constexpr sampler densitySampler(filter::linear, mip_filter::linear,
                                      address::clamp_to_edge);
    return densityLookup.sample(densitySampler, float2(coordinate, 0.0)).a * fog.colorDensity.a;
}

float3 apply_atmospheric_fog(float3 sceneColor, float coordinate,
                            texture2d<float> densityLookup,
                            constant AtmosphericFogUniforms &fog) {
    // With planar fog off, the original packed combiners at fog.c:660-684
    // produce (atmosphericColor * amount, amount). Their ONE/INVSRCALPHA
    // pass blends over the previously clamped 8-bit scene framebuffer.
    float amount = atmospheric_fog_amount(coordinate, densityLookup, fog);
    return fog.colorDensity.rgb * amount + clamp(sceneColor, 0.0, 1.0) * (1.0 - amount);
}
#endif
