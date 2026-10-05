// Concatenate after Teleporter.metal: the shared source already defines the
// 28-byte vertex, 112-byte frame, 368-byte material, UV animation and combiner
// helpers. This pass has its own BSP visibility and source draw-state rules.
struct TransparentBspVaryings {
    float4 position [[position]];
    float2 uv0, uv1, uv2, uv3;
    float fade;
    float fogCoordinate;
};

float transparent_bsp_vertex_fade(float3 position, float3 normal,
    constant TeleporterFrameUniforms &frame, uint mode) {
    // Original unlit BSP generic program24 (runtime handle25): D0.a is
    // atmospheric visibility, D1.rgb is abs(dot(decodedNormal,-forward))*it.
    // Planar fog is absent in Blood Gulch; maximum density remains raw .4.
    float coordinate = dot(float4(position, 1.0), frame.fogCoordinatePlane);
    float visibility = 1.0-clamp(coordinate, 0.0, 1.0)*frame.fogParameters.x;
    float facing = abs(dot(normal, -frame.cameraForwardExposure.xyz));
    if (mode == 0) return clamp(visibility, 0.0, 1.0);
    if (mode == 1) return clamp((1.0-facing)*visibility, 0.0, 1.0);
    return clamp(facing*visibility, 0.0, 1.0);
}

vertex TransparentBspVaryings transparent_bsp_vertex(uint index [[vertex_id]],
    const device TeleporterVertex *vertices [[buffer(0)]],
    constant TeleporterFrameUniforms &frame [[buffer(1)]],
    const device packed_float3 *normals [[buffer(2)]],
    constant TeleporterMaterialUniforms &material [[buffer(3)]]) {
    TeleporterVertex v = vertices[index];
    float3 position = float3(v.position);
    float time = frame.fogParameters.y;
    return {frame.viewProjection*float4(position, 1.0),
            teleporter_uv(float2(v.uv), 0, time, material),
            teleporter_uv(float2(v.uv), 1, time, material),
            teleporter_uv(float2(v.uv), 2, time, material),
            teleporter_uv(float2(v.uv), 3, time, material),
            transparent_bsp_vertex_fade(position, float3(normals[index]),
                                        frame, material.padding[0]),
            dot(float4(position, 1.0), frame.fogCoordinatePlane)};
}

struct TransparentBspFragmentOutput { float4 color [[color(0)]]; uint sampleMask [[sample_mask]]; };

fragment TransparentBspFragmentOutput transparent_bsp_fragment(TransparentBspVaryings in [[stage_in]],
    texture2d<float> texture0 [[texture(0)]], texture2d<float> texture1 [[texture(1)]],
    texture2d<float> texture2 [[texture(2)]], texture2d<float> texture3 [[texture(3)]],
    texture2d<float> densityLookup [[texture(4)]],
    constant TeleporterFrameUniforms &frame [[buffer(0)]],
    constant TeleporterMaterialUniforms &material [[buffer(1)]],
    constant AtmosphericFogUniforms &fog [[buffer(2)]]) {
    constexpr sampler repeating(filter::linear, mip_filter::linear, address::repeat);
    float4 color;
    if (material.kind == 3) color = texture0.sample(repeating, in.uv0);
    else if (material.kind == 1) color = teleporter_plasma(
        texture0.sample(repeating, in.uv0), texture1.sample(repeating, in.uv1),
        texture2.sample(repeating, in.uv2), texture3.sample(repeating, in.uv3),
        material.constantColor[0], material.constantColor[1]);
    else { discard_fragment(); return {float4(0.0), 0xffffffffu}; }
    // generic_create supplies passthrough when explicit stage_count=0, then
    // transparent_geometry adds RGB*D0.a (fade0) or RGB*D1.r (fade2). Alpha
    // is preserved but the source pipeline writes RGB only with ONE+ONE.
    float3 contribution = clamp(color.rgb*in.fade, 0.0, 1.0);
    // Authored is_decal BSP executes before the separate opaque fog pass,
    // despite applying generic vertex fog itself. The preview's opaque fog
    // runs inline, so preserve that second attenuation on these overlays.
    if (material.padding[1]) contribution *= 1.0-atmospheric_fog_amount(
        in.fogCoordinate, densityLookup, fog);
    return {float4(contribution, clamp(color.a, 0.0, 1.0)), 0xffffffffu};
}

// Host: RGB ONE+ONE, no alpha write, LEQUAL/no depth write; original CW
// front winding/back cull except two_sided shields. Z bias(-8,-2) only for
// the authored is_decal materials (cap_moss01b/greenlight); base lights0.
