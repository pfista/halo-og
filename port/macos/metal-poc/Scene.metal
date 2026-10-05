#include <metal_stdlib>
using namespace metal;

struct Vertex { packed_float3 position; packed_float2 uv; packed_float2 lightmapUV; };
struct Uniforms { float4x4 viewProjection; uint mode; float exposure; float2 pad; };
struct MaterialUniforms {
    uint alphaTest, shaderType, detailFunction, microFunction;
    float4 detailScale01;
    float4 detailScale2;
};
struct Varyings { float4 position [[position]]; float2 uv; float2 lightmapUV; float fogCoordinate; };

// Mirrors the diffuse-texture RGB combiners in
// rasterizer_xbox_environment.c:1652-1694. General combiner results clamp
// to [-1,1]; the next unsigned input discards their negative component.
float3 environment_detail_function(float3 base, float3 detail, uint function) {
    base = max(base, 0.0);
    detail = max(detail, 0.0);
    float3 result;
    if (function == 0) result = 2.0 * base * detail;
    else if (function == 1) result = base * detail;
    else result = base + 2.0 * detail - 1.0;
    return clamp(result, -1.0, 1.0);
}

float4 environment_diffuse(float4 base, float4 primary, float4 secondary,
                           float4 micro, constant MaterialUniforms &material) {
    // Normal materials select primary/secondary with secondary detail alpha;
    // blended and blended-base-specular materials use the base-map alpha.
    // The Blood Gulch ground's alpha is its sand/grass material mask.
    float mask = material.shaderType == 0 ? secondary.a : base.a;
    float3 detail = secondary.rgb * (1.0 - mask) + primary.rgb * mask;
    float3 color = environment_detail_function(base.rgb, detail, material.detailFunction);
    color = environment_detail_function(color, micro.rgb, material.microFunction);
    // This alpha is the original diffuse pass's specular mask. The original
    // geometry cutout runs in the separate lightmap/depth pass, not here.
    float specularMask;
    if (material.shaderType == 0)
        specularMask = base.a * ((1.0 - secondary.a) * secondary.a + secondary.a * primary.a);
    else if (material.shaderType == 1)
        specularMask = secondary.a * (1.0 - base.a) + primary.a * base.a;
    else specularMask = base.a;
    return float4(clamp(color, 0.0, 1.0), specularMask * micro.a);
}

vertex Varyings scene_vertex(uint index [[vertex_id]],
                            const device Vertex *vertices [[buffer(0)]],
                            constant Uniforms &uniforms [[buffer(1)]],
                            constant AtmosphericFogUniforms &fog [[buffer(2)]]) {
    Vertex v = vertices[index];
    return { uniforms.viewProjection * float4(float3(v.position), 1),
             float2(v.uv), float2(v.lightmapUV),
             atmospheric_fog_coordinate(float3(v.position), fog) };
}

// Match ANGLE's Apple Metal all-samples fragment output workaround.
struct SceneFragmentOutput { float4 color [[color(0)]]; uint sampleMask [[sample_mask]]; };

fragment SceneFragmentOutput scene_fragment(Varyings in [[stage_in]],
                               texture2d<float> base [[texture(0)]],
                               texture2d<float> lightmap [[texture(1)]],
                               texture2d<float> primary [[texture(2)]],
                               texture2d<float> secondary [[texture(3)]],
                               texture2d<float> micro [[texture(4)]],
                               texture2d<float> densityLookup [[texture(5)]],
                               texture2d<float> cutout [[texture(6)]],
                               constant Uniforms &uniforms [[buffer(0)]],
                               constant MaterialUniforms &material [[buffer(1)]],
                               constant AtmosphericFogUniforms &fog [[buffer(2)]]) {
    constexpr sampler repeating(filter::linear, mip_filter::linear, address::repeat);
    constexpr sampler clamped(filter::linear, address::clamp_to_edge);
    float4 albedo = base.sample(repeating, in.uv);
    if (material.alphaTest && cutout.sample(repeating, in.uv * material.detailScale2.zw).a < 0.5) discard_fragment();
    float4 primaryDetail = primary.sample(repeating, in.uv * material.detailScale01.xy);
    float4 secondaryDetail = secondary.sample(repeating, in.uv * material.detailScale01.zw);
    float4 microDetail = micro.sample(repeating, in.uv * material.detailScale2.xy);
    float4 diffuse = environment_diffuse(albedo, primaryDetail, secondaryDetail, microDetail, material);
    float3 lighting = lightmap.sample(clamped, in.lightmapUV).rgb;
    float3 color = diffuse.rgb * lighting;
    if (uniforms.mode == 1) color = albedo.rgb;
    if (uniforms.mode == 2) color = lighting;
    if (uniforms.mode == 3) color = diffuse.rgb;
    color *= uniforms.exposure;
    if (uniforms.mode == 0) color = apply_atmospheric_fog(color, in.fogCoordinate, densityLookup, fog);
    return {float4(color, 1), 0xffffffffu};
}
