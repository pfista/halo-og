#include <metal_stdlib>
using namespace metal;

// Blood Gulch's original scenario scenery. Shared vertices remain 28 bytes;
// the additional packed normal stream preserves the generic model angle fade.
struct TeleporterVertex { packed_float3 position; packed_float2 uv, lightmapUV; };
struct TeleporterFrameUniforms {
    float4x4 viewProjection;
    float4 cameraForwardExposure;
    float4 fogCoordinatePlane;
    float4 fogParameters; // raw maximum density, original game seconds, 0, 0
};
struct TeleporterMaterialUniforms {
    uint kind; uint padding[3]; //1 seven-stage generic plasma,2 Chicago cone
    float4 scaleOffset[4];
    float4 uAnimation[4], vAnimation[4], rAnimation[4];
    float4 rotationCenter[4];
    float4 constantColor[2]; //packed original color0 lower bounds, stages0/6
};
struct TeleporterVaryings {
    float4 position [[position]];
    float2 uv0, uv1, uv2, uv3;
    float fade;
};

// periodic_functions.c: byte table1024, x=i*.027343748, lookup time*25.6.
// This includes negative-period lookup and the original wrap interpolation;
// fract(time/period) does not reproduce the authored animation.
float teleporter_slide_value(uint index) {
    float x = float(index & 1023u) * 0.027343748f;
    return float(uint(clamp(trunc(fmod(x, 1.0f) * 255.0f), 0.0f, 255.0f))) / 255.0f;
}
float teleporter_periodic_slide(float time) {
    float scaled = time * 25.6f;
    float fraction = fmod(scaled, 1.0f);
    uint index = uint(int(scaled-fraction)) & 1023u;
    float first = teleporter_slide_value(index);
    float second = teleporter_slide_value(index+1u);
    if (first > .75f && second < .25f) second += 1.0f;
    float value = (1.0f-fraction)*first + second*fraction;
    return value > 1.0f ? value-1.0f : value;
}
float teleporter_animation(float4 animation, float time) {
    float period = animation.y == 0.0f ? 1.0f : animation.y;
    float value = animation.x == 0.0f ? 1.0f :
                  teleporter_periodic_slide((animation.z+time)/period);
    return value*animation.w;
}
float2 teleporter_uv(float2 uv, uint map, float time,
                    constant TeleporterMaterialUniforms &material) {
    float4 transform = material.scaleOffset[map];
    float4 rotation = material.rotationCenter[map];
    float2 offset = transform.zw - rotation.yz + float2(
        teleporter_animation(material.uAnimation[map],time),
        teleporter_animation(material.vAnimation[map],time));
    float angle = (rotation.x + teleporter_animation(material.rAnimation[map],time)) *
                  (M_PI_F / 180.0f);
    float c = cos(angle), s = sin(angle);
    float2 coordinate = uv*transform.xy + offset;
    return float2(c*coordinate.x-s*coordinate.y,
                  s*coordinate.x+c*coordinate.y) + rotation.yz;
}

float teleporter_vertex_fade(float3 position, float3 normal,
                            constant TeleporterFrameUniforms &frame) {
    // Original generic model vertex program47: normalize the transformed
    // model normal, abs(dot(normal,-c[-91].xyz)), then multiply by visibility.
    // Blood Gulch has no planar fog; c[-85].x is raw .4, not packed102/255.
    float facing = abs(dot(normalize(normal),-frame.cameraForwardExposure.xyz));
    float coordinate = dot(float4(position,1.0),frame.fogCoordinatePlane);
    float visibility = 1.0f-clamp(coordinate,0.0f,1.0f)*frame.fogParameters.x;
    return clamp(facing*visibility,0.0f,1.0f);
}

float4 teleporter_plasma(float4 t0, float4 t1, float4 t2, float4 t3,
                         float4 c0, float4 c6) {
    // Direct equations from the authored generic selectors, preserving signed
    // general-combiner clamps, unsigned reads, MSB mux and separate RGB/alpha.
    float3 color = clamp(float3((1.0f-c0.a)*t2.a+c0.a*t0.a),-1.0f,1.0f);
    float alpha = clamp((1.0f-c0.b)*.5f+c0.b*t1.a,-1.0f,1.0f);
    color = clamp(t3.a*.5f+(1.0f-t3.a)*max(color,0.0f),-1.0f,1.0f);
    alpha = clamp(t3.a*.5f+(1.0f-t3.a)*max(alpha,0.0f),-1.0f,1.0f);
    float3 nextColor = clamp(max(color,0.0f)+(.5f-alpha),-1.0f,1.0f);
    alpha = clamp(max(alpha,0.0f)+(.5f-color.b),-1.0f,1.0f);
    color = nextColor;
    float a = max(alpha,0.0f), blue = max(color.b,0.0f);
    alpha = clamp(4.0f*(alpha>=.5f ? blue*blue : a*a),-1.0f,1.0f);
    float expanded = 2.0f*max(alpha,0.0f)-1.0f;
    alpha = clamp(alpha>=.5f ? expanded*expanded : 0.0f,-1.0f,1.0f);
    a = max(alpha,0.0f);
    alpha = clamp(a+a*(1.0f-a),-1.0f,1.0f);
    color = clamp(max(alpha,0.0f)*t3.rgb+c6.rgb*t3.rgb,-1.0f,1.0f);
    return float4(max(color,0.0f),max(alpha,0.0f));
}
float4 teleporter_cone(float4 t0, float4 t1, float4 t2) {
    // Chicago functions(2,2),(2,2),(0,0): RGBA product of allthree maps.
    return clamp(clamp(t0*t1,-1.0f,1.0f)*t2,-1.0f,1.0f);
}

vertex TeleporterVaryings teleporter_vertex(uint index [[vertex_id]],
    const device TeleporterVertex *vertices [[buffer(0)]],
    constant TeleporterFrameUniforms &frame [[buffer(1)]],
    const device packed_float3 *normals [[buffer(2)]],
    constant TeleporterMaterialUniforms &material [[buffer(3)]]) {
    TeleporterVertex v = vertices[index];
    float3 position = float3(v.position);
    float time = frame.fogParameters.y;
    return {frame.viewProjection*float4(position,1.0),
            teleporter_uv(float2(v.uv),0,time,material),
            teleporter_uv(float2(v.uv),1,time,material),
            teleporter_uv(float2(v.uv),2,time,material),
            teleporter_uv(float2(v.uv),3,time,material),
            teleporter_vertex_fade(position,float3(normals[index]),frame)};
}

struct TeleporterFragmentOutput { float4 color [[color(0)]]; uint sampleMask [[sample_mask]]; };

fragment TeleporterFragmentOutput teleporter_fragment(TeleporterVaryings in [[stage_in]],
    texture2d<float> texture0 [[texture(0)]], texture2d<float> texture1 [[texture(1)]],
    texture2d<float> texture2 [[texture(2)]], texture2d<float> texture3 [[texture(3)]],
    constant TeleporterFrameUniforms &frame [[buffer(0)]],
    constant TeleporterMaterialUniforms &material [[buffer(1)]]) {
    constexpr sampler repeating(filter::linear,mip_filter::linear,address::repeat);
    float4 t0 = texture0.sample(repeating,in.uv0), t1 = texture1.sample(repeating,in.uv1);
    float4 t2 = texture2.sample(repeating,in.uv2), t3 = texture3.sample(repeating,in.uv3);
    float4 color;
    if (material.kind == 1) color = teleporter_plasma(t0,t1,t2,t3,
                                                   material.constantColor[0],material.constantColor[1]);
    else if (material.kind == 2) color = teleporter_cone(t0,t1,t2);
    else { discard_fragment(); return {float4(0.0), 0xffffffffu}; }
    // Original final added RGB stage for blendADD/fade_parallel selects D1.red;
    // fixed function then adds ONE*color + ONE*destination with RGB writes only.
    return {float4(clamp(color.rgb*in.fade,0.0f,1.0f)*frame.cameraForwardExposure.w,color.a), 0xffffffffu};
}
