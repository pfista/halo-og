// Isolated native Metal BSP viewer. Does not link Halo, SDL, OpenGL or ANGLE.
#import <Cocoa/Cocoa.h>
#import <MetalKit/MetalKit.h>
#import <simd/simd.h>
#import <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <vector>

static void require(bool value, NSString *message) {
    if (!value) { fprintf(stderr, "Metal POC: %s\n", message.UTF8String); exit(1); }
}
static NSData *readFile(NSString *path) {
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
    require(data != nil, error.localizedDescription ?: path);
    return data;
}

static NSString *sha256(NSData *data) {
    require(data.length <= UINT32_MAX, @"File too large to hash");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *result = [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (unsigned char byte : digest) [result appendFormat:@"%02x", byte];
    return result;
}

static NSUInteger textureDimension(id value) {
    require([value isKindOfClass:NSNumber.class], @"Invalid texture dimensions");
    double number = [value doubleValue];
    require(std::isfinite(number) && number >= 1 && number <= 4096 && std::floor(number) == number,
            @"Invalid texture dimensions");
    return (NSUInteger)number;
}

static bool textureFilenameValid(id value) {
    if (![value isKindOfClass:NSString.class]) return false;
    NSString *name = value;
    return name.length && ![name isEqualToString:@"."] && ![name isEqualToString:@".."] &&
        [name isEqualToString:name.lastPathComponent];
}

struct TextureMipLevel {
    NSUInteger width, height;
    NSData *pixels;
    MTLPixelFormat format;
    NSUInteger bytesPerRow;
};

// Read the exact exported levels. In particular, authored detail-map mipmaps
// fade toward neutral gray; ordinary GPU mip generation loses that behavior.
static std::vector<TextureMipLevel> loadTextureMipmaps(NSDictionary *texture, NSString *scene) {
    require([texture isKindOfClass:NSDictionary.class], @"Invalid texture description");
    NSUInteger width = textureDimension(texture[@"width"]), height = textureDimension(texture[@"height"]);
    require(textureFilenameValid(texture[@"file"]), @"Invalid texture filename");
    bool compressed = texture[@"native_format"] != nil;
    if (compressed) {
        require([texture[@"native_format"] isEqual:@"bc1_rgba"] &&
                [texture[@"source_format"] isKindOfClass:NSNumber.class] &&
                [texture[@"source_format"] doubleValue] == 14 && ![texture[@"swizzled"] boolValue],
                @"Unsupported native texture format");
        require(textureFilenameValid(texture[@"native_file"]), @"Invalid native texture filename");
    }
    NSArray *mipmaps = compressed ? texture[@"native_mipmaps"] : texture[@"mipmaps"];
    require([mipmaps isKindOfClass:NSArray.class] && mipmaps.count,
            @"Scene lacks authored mipmaps; re-export it with the current exporter");
    NSUInteger maximumLevels = 1;
    for (NSUInteger extent = compressed ? std::max(width, height) / 4 : std::max(width, height);
         extent > 1; extent >>= 1) maximumLevels++;
    require(mipmaps.count <= maximumLevels, @"Too many texture mipmaps");
    if (compressed) require([texture[@"mipmaps"] isKindOfClass:NSArray.class] &&
                            [texture[@"mipmaps"] count] == mipmaps.count,
                            @"Native mipmaps differ from authored level count");
    std::vector<TextureMipLevel> levels;
    for (NSUInteger level = 0; level < mipmaps.count; level++) {
        NSDictionary *mip = mipmaps[level];
        require([mip isKindOfClass:NSDictionary.class], @"Invalid texture mipmap");
        NSUInteger mipWidth = textureDimension(mip[@"width"]), mipHeight = textureDimension(mip[@"height"]);
        require(mipWidth == std::max((NSUInteger)1, width >> level) &&
                mipHeight == std::max((NSUInteger)1, height >> level), @"Invalid texture mipmap dimensions");
        NSString *filename = mip[@"file"];
        require(textureFilenameValid(filename), @"Invalid texture mipmap filename");
        if (level == 0) require([filename isEqualToString:compressed ? texture[@"native_file"] : texture[@"file"]],
                               @"Mipmap zero filename mismatch");
        NSData *pixels = readFile([scene stringByAppendingPathComponent:filename]);
        NSUInteger pitch = compressed ? ((mipWidth + 3) / 4) * 8 : mipWidth * 4;
        NSUInteger rows = compressed ? (mipHeight + 3) / 4 : mipHeight;
        require(pixels.length == pitch * rows, @"Invalid texture mipmap byte count");
        levels.push_back({mipWidth, mipHeight, pixels,
                         compressed ? MTLPixelFormatBC1_RGBA : MTLPixelFormatRGBA8Unorm, pitch});
    }
    return levels;
}

static NSUInteger parseInteger(const char *value, NSUInteger maximum, NSString *message) {
    char *end = nullptr;
    unsigned long long number = strtoull(value, &end, 10);
    require(end != value && *end == '\0' && number >= 1 && number <= maximum, message);
    return (NSUInteger)number;
}

static float parseVerticalFov(const char *value) {
    char *end = nullptr;
    double number = strtod(value, &end);
    require(end != value && *end == '\0' && std::isfinite(number) && number >= 1 && number < 179,
            @"Vertical FOV must be between 1 and 179 degrees");
    return (float)number;
}

static float finiteNumber(id value, NSString *message) {
    require([value isKindOfClass:NSNumber.class], message);
    float number = [value floatValue];
    require(std::isfinite(number), message);
    return number;
}

static simd_float4 float4Array(id value, NSString *message) {
    require([value isKindOfClass:NSArray.class] && [value count] == 4, message);
    simd_float4 result;
    for (NSUInteger i = 0; i < 4; i++) result[i] = finiteNumber(value[i], message);
    return result;
}

static id<MTLRenderPipelineState> scenePipeline(id<MTLDevice> device, id<MTLLibrary> library,
                                              NSString *vertex, NSString *fragment,
                                              bool blend, MTLBlendFactor source,
                                              MTLBlendFactor destination, bool rgbOnly) {
    MTLRenderPipelineDescriptor *desc = [MTLRenderPipelineDescriptor new];
    desc.label = [NSString stringWithFormat:@"Halo preview / %@", fragment];
    desc.vertexFunction = [library newFunctionWithName:vertex];
    desc.fragmentFunction = [library newFunctionWithName:fragment];
    require(desc.vertexFunction && desc.fragmentFunction, @"Missing Metal shader entry point");
    MTLRenderPipelineColorAttachmentDescriptor *color = desc.colorAttachments[0];
    color.pixelFormat = MTLPixelFormatBGRA8Unorm;
    color.blendingEnabled = blend;
    color.sourceRGBBlendFactor = source;
    color.destinationRGBBlendFactor = destination;
    color.rgbBlendOperation = MTLBlendOperationAdd;
    color.writeMask = rgbOnly ? MTLColorWriteMaskRed | MTLColorWriteMaskGreen | MTLColorWriteMaskBlue : MTLColorWriteMaskAll;
    desc.depthAttachmentPixelFormat = MTLPixelFormatDepth32Float;
    NSError *error = nil;
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:desc error:&error];
    require(pipeline != nil, error.localizedDescription ?: @"Metal pipeline creation failed");
    return pipeline;
}

struct Vertex { float x, y, z, u, v, lu, lv; };
static_assert(sizeof(Vertex) == 28, "Scene vertex ABI");
struct Uniforms { simd_float4x4 viewProjection; uint32_t mode; float exposure; float pad[2]; };
static_assert(sizeof(Uniforms) == 80, "Shader uniform ABI");
struct MaterialUniforms {
    uint32_t alphaTest, shaderType, detailFunction, microFunction;
    simd_float4 detailScale01, detailScale2;
};
static_assert(sizeof(MaterialUniforms) == 48, "Environment material shader ABI");
struct AtmosphericFogUniforms { simd_float4 coordinatePlane, colorDensity; };
static_assert(sizeof(AtmosphericFogUniforms) == 32, "Atmospheric fog ABI");
struct SkyFrameUniforms { simd_float4x4 viewProjection; simd_float4 cameraPositionExposure, planarFog; };
struct SkyMaterialUniforms { uint32_t kind, pad[3]; simd_float4 scale01, scale2, offset01, offset2; };
static_assert(sizeof(SkyFrameUniforms) == 96 && sizeof(SkyMaterialUniforms) == 80, "Sky shader ABI");
struct TeleporterFrameUniforms {
    simd_float4x4 viewProjection;
    simd_float4 cameraForwardExposure, fogCoordinatePlane, fogParameters;
};
struct TeleporterMaterialUniforms {
    uint32_t kind, pad[3];
    simd_float4 scaleOffset[4], uAnimation[4], vAnimation[4], rAnimation[4], rotationCenter[4], constantColor[2];
};
static_assert(sizeof(TeleporterFrameUniforms) == 112 && sizeof(TeleporterMaterialUniforms) == 368,
              "Teleporter shader ABI");
struct Mesh { NSUInteger first, count, base, lightmap, detail[3], alphaMap; MaterialUniforms material; };
struct SkyMesh { NSUInteger first, count, textures[3]; SkyMaterialUniforms material; };
struct DecalMesh { NSUInteger first, count, texture; simd_float4 tintIntensity; };
struct TeleporterMesh { NSUInteger first, count, textures[4], placement; TeleporterMaterialUniforms material; };
struct TransparentBspMesh {
    NSUInteger first, count, textures[4];
    TeleporterMaterialUniforms material;
    bool twoSided, isDecal;
};

@interface SceneRenderer : NSObject<MTKViewDelegate> {
@public
    id<MTLDevice> device;
    id<MTLCommandQueue> queue;
    id<MTLRenderPipelineState> pipeline, skyPipeline, decalPipeline, teleporterPipeline, transparentBspPipeline;
    id<MTLDepthStencilState> depthState, skyDepthState, overlayDepthState;
    id<MTLBuffer> vertices, indices, teleporterNormals;
    NSMutableArray<id<MTLTexture>> *textures;
    std::vector<Mesh> meshes;
    std::vector<SkyMesh> skyMeshes;
    std::vector<DecalMesh> decalMeshes;
    std::vector<TeleporterMesh> teleporterMeshes;
    std::vector<TransparentBspMesh> transparentBspMeshes;
    simd_float3 position, initialPosition;
    float yaw, pitch, initialYaw, exposure, verticalFov;
    bool keys[128], wireframe;
    uint32_t mode;
    double lastTime, startTime, animationTime;
    bool fixedAnimationTime;
    NSUInteger frames, triangleCount, opaqueTriangleCount, bspTriangleCount, skyTriangleCount,
        decalTriangleCount, teleporterTriangleCount, transparentBspTriangleCount,
        teleporterPlacementCount, textureMipLevelCount, compressedTextureCount,
        captureWidth, captureHeight, fogDensityTexture;
    float fogStart, fogEnd, fogDensity, fogRawDensity;
    simd_float3 fogColor, clearColorRGB;
    bool fogEnabled;
    NSString *mapName, *sourceSHA256, *sceneSHA256, *shaderSHA256, *hostSHA256;
    NSDictionary *shaderSourcesSHA256;
    NSTextField *help;
}
- (instancetype)initWithScene:(NSString *)scene shader:(NSString *)shader;
- (void)resetCamera;
- (void)inspectTeleporter;
- (void)encode:(id<MTLCommandBuffer>)command pass:(MTLRenderPassDescriptor *)pass
          size:(CGSize)size;
- (void)capture:(NSString *)path frames:(NSUInteger)count;
@end

static simd_float4x4 cameraMatrix(simd_float3 eye, float yaw, float pitch, float aspect, float verticalFov,
                                 float near = 0.0625f, float far = 1024.0f) {
    // Original rasterizer global defaults, also verified against captured c2/c3.
    // Blood Gulch's .4 atmospheric density leaves the far plane at 1024.
    simd_float3 forward = {cosf(yaw) * cosf(pitch), sinf(yaw) * cosf(pitch), sinf(pitch)};
    simd_float3 right = simd_normalize(simd_cross(forward, (simd_float3){0, 0, 1}));
    simd_float3 up = simd_cross(right, forward);
    simd_float4x4 view = {{
        {right.x, up.x, -forward.x, 0}, {right.y, up.y, -forward.y, 0},
        {right.z, up.z, -forward.z, 0},
        {-simd_dot(right, eye), -simd_dot(up, eye), simd_dot(forward, eye), 1}
    }};
    float y = 1.0f / tanf(verticalFov * M_PI / 360.0f);
    simd_float4x4 projection = {{
        {y / aspect, 0, 0, 0}, {0, y, 0, 0},
        {0, 0, far / (near - far), -1}, {0, 0, near * far / (near - far), 0}
    }};
    return simd_mul(projection, view);
}

@implementation SceneRenderer
- (instancetype)initWithScene:(NSString *)scene shader:(NSString *)shader {
    self = [super init];
    if (!self) return nil;
    hostSHA256 = sha256(readFile(NSBundle.mainBundle.executablePath));
    NSError *error = nil;
    NSData *manifestData = readFile([scene stringByAppendingPathComponent:@"scene.json"]);
    NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:manifestData options:0 error:&error];
    require([manifest isKindOfClass:NSDictionary.class] && [manifest[@"version"] intValue] == 1,
            @"Unsupported scene manifest");
    device = MTLCreateSystemDefaultDevice();
    require(device != nil, @"No Metal device available");
    queue = [device newCommandQueue];
    require(queue != nil, @"Could not create Metal command queue");
    NSMutableString *source = [NSMutableString string];
    NSMutableDictionary *sourceHashes = [NSMutableDictionary dictionary];
    NSString *shaderFolder = shader.stringByDeletingLastPathComponent;
    for (NSString *name in @[@"Fog.metal", @"Scene.metal", @"Sky.metal", @"Decal.metal", @"Teleporter.metal", @"TransparentBsp.metal"]) {
        NSString *path = [name isEqualToString:@"Scene.metal"] ? shader : [shaderFolder stringByAppendingPathComponent:name];
        NSData *data = readFile(path);
        NSString *part = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
        require(part != nil, @"Invalid UTF-8 Metal source");
        sourceHashes[name] = sha256(data);
        // Runtime Metal compilation accepts one source string; Fog is already
        // first in that string, so remove the local filesystem include only.
        part = [part stringByReplacingOccurrencesOfString:@"#include \"Fog.metal\"" withString:@""];
        [source appendFormat:@"\n%@\n", part];
    }
    sceneSHA256 = sha256(manifestData);
    shaderSHA256 = sha256([source dataUsingEncoding:NSUTF8StringEncoding]);
    shaderSourcesSHA256 = [sourceHashes copy];
    sourceSHA256 = manifest[@"source_sha256"];
    MTLCompileOptions *options = [MTLCompileOptions new];
    options.fastMathEnabled = NO;
    options.preserveInvariance = YES;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    require(library != nil, error.localizedDescription ?: @"Metal shader compilation failed");
    pipeline = scenePipeline(device, library, @"scene_vertex", @"scene_fragment", false,
                             MTLBlendFactorOne, MTLBlendFactorZero, false);
    skyPipeline = scenePipeline(device, library, @"sky_vertex", @"sky_fragment", true,
                                MTLBlendFactorSourceAlpha, MTLBlendFactorOneMinusSourceAlpha, true);
    decalPipeline = scenePipeline(device, library, @"decal_vertex", @"decal_fragment", true,
                                  MTLBlendFactorOne, MTLBlendFactorOne, true);
    teleporterPipeline = scenePipeline(device, library, @"teleporter_vertex", @"teleporter_fragment", true,
                                       MTLBlendFactorOne, MTLBlendFactorOne, true);
    transparentBspPipeline = scenePipeline(device, library, @"transparent_bsp_vertex", @"transparent_bsp_fragment", true,
                                           MTLBlendFactorOne, MTLBlendFactorOne, true);
    MTLDepthStencilDescriptor *depth = [MTLDepthStencilDescriptor new];
    depth.depthCompareFunction = MTLCompareFunctionLessEqual;
    depth.depthWriteEnabled = YES;
    depthState = [device newDepthStencilStateWithDescriptor:depth];
    depth.depthCompareFunction = MTLCompareFunctionAlways;
    depth.depthWriteEnabled = NO;
    skyDepthState = [device newDepthStencilStateWithDescriptor:depth];
    depth.depthCompareFunction = MTLCompareFunctionLessEqual;
    overlayDepthState = [device newDepthStencilStateWithDescriptor:depth];
    require(depthState && skyDepthState && overlayDepthState, @"Could not create depth states");
    NSData *v = readFile([scene stringByAppendingPathComponent:@"vertices.bin"]);
    NSData *idx = readFile([scene stringByAppendingPathComponent:@"indices.bin"]);
    require(v.length && v.length % sizeof(Vertex) == 0 && idx.length && idx.length % 12 == 0,
            @"Invalid geometry buffer size");
    const uint32_t *iv = (const uint32_t *)idx.bytes;
    for (NSUInteger i = 0; i < idx.length / 4; i++)
        require(iv[i] < v.length / sizeof(Vertex), @"Index outside vertex buffer");
    vertices = [device newBufferWithBytes:v.bytes length:v.length options:MTLResourceStorageModeShared];
    indices = [device newBufferWithBytes:idx.bytes length:idx.length options:MTLResourceStorageModeShared];
    require(vertices && indices, @"Geometry buffer allocation failed");
    textures = [NSMutableArray array];
    for (NSDictionary *t in manifest[@"textures"]) {
        std::vector<TextureMipLevel> levels = loadTextureMipmaps(t, scene);
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:levels[0].format
            width:levels[0].width height:levels[0].height mipmapped:levels.size() > 1];
        td.mipmapLevelCount = levels.size();
        td.storageMode = MTLStorageModeShared;
        td.usage = MTLTextureUsageShaderRead;
        id<MTLTexture> tex = [device newTextureWithDescriptor:td];
        require(tex != nil, @"Texture allocation failed");
        tex.label = t[@"name"];
        for (NSUInteger level = 0; level < levels.size(); level++) {
            const TextureMipLevel &mip = levels[level];
            [tex replaceRegion:MTLRegionMake2D(0, 0, mip.width, mip.height) mipmapLevel:level
                 withBytes:mip.pixels.bytes bytesPerRow:mip.bytesPerRow];
        }
        textureMipLevelCount += levels.size();
        if (levels[0].format == MTLPixelFormatBC1_RGBA) compressedTextureCount++;
        [textures addObject:tex];
    }
    NSDictionary *fog = manifest[@"fog"];
    require([fog isKindOfClass:NSDictionary.class] && [fog[@"color"] count] == 3 &&
            [fog[@"planar_mode"] intValue] == 0, @"Unsupported atmospheric fog manifest");
    NSArray *clear = manifest[@"clear_color"] ?: fog[@"color"];
    require([clear isKindOfClass:NSArray.class] && clear.count == 3, @"Invalid original clear color");
    for (NSUInteger i = 0; i < 3; i++) {
        clearColorRGB[i] = finiteNumber(clear[i], @"Invalid original clear color");
        require(clearColorRGB[i] >= 0 && clearColorRGB[i] <= 1, @"Invalid original clear color");
    }
    fogEnabled = [fog[@"enabled"] boolValue];
    fogStart = finiteNumber(fog[@"start"], @"Invalid fog start");
    fogEnd = finiteNumber(fog[@"end"], @"Invalid fog end");
    fogDensity = finiteNumber(fog[@"density"], @"Invalid fog density");
    require(fogDensity >= 0 && fogDensity <= 1 && (!fogEnabled || fogEnd > fogStart), @"Invalid fog range or density");
    for (NSUInteger i = 0; i < 3; i++) {
        fogColor[i] = finiteNumber(fog[@"color"][i], @"Invalid fog color");
        require(fogColor[i] >= 0 && fogColor[i] <= 1, @"Invalid fog color");
    }
    fogRawDensity = fog[@"source_density"] ? finiteNumber(fog[@"source_density"], @"Invalid raw fog density") : fogDensity;
    fogRawDensity = fogEnabled ? std::clamp(fogRawDensity <= 0 ? 1.0f : fogRawDensity, 0.0f, 1.0f) : 0;
    fogDensityTexture = [fog[@"density_texture"] unsignedIntegerValue];
    require(fogDensityTexture < textures.count, @"Invalid fog lookup texture");
    bspTriangleCount = [manifest[@"bsp_triangles"] unsignedIntegerValue];
    NSMutableArray *opaqueMeshes = [manifest[@"meshes"] mutableCopy];
    require(opaqueMeshes != nil, @"Missing opaque meshes");
    NSMutableSet *placements = [NSMutableSet set];
    for (NSDictionary *m in manifest[@"teleporter_meshes"]) {
        require([m isKindOfClass:NSDictionary.class] && m[@"kind"] && m[@"placement_index"],
                @"Invalid teleporter mesh description");
        [placements addObject:m[@"placement_index"]];
        if ([m[@"kind"] unsignedIntValue] == 0) [opaqueMeshes addObject:m];
    }
    teleporterPlacementCount = placements.count;
    for (NSDictionary *m in opaqueMeshes) {
        require([m[@"detail_textures"] count] == 3 && [m[@"detail_scales"] count] == 6 &&
                m[@"shader_type"] && m[@"detail_function"] && m[@"micro_function"],
                @"Scene lacks environment detail maps; re-export it with the current exporter");
        Mesh mesh = {};
        mesh.first = [m[@"first_index"] unsignedIntegerValue]; mesh.count = [m[@"index_count"] unsignedIntegerValue];
        mesh.base = [m[@"base_texture"] unsignedIntegerValue]; mesh.lightmap = [m[@"lightmap_texture"] unsignedIntegerValue];
        mesh.alphaMap = m[@"alpha_test_texture"] ? [m[@"alpha_test_texture"] unsignedIntegerValue] : mesh.base;
        mesh.material.alphaTest = [m[@"alpha_test"] boolValue] ? 1u : 0u;
        mesh.material.shaderType = [m[@"shader_type"] unsignedIntValue];
        mesh.material.detailFunction = [m[@"detail_function"] unsignedIntValue];
        mesh.material.microFunction = [m[@"micro_function"] unsignedIntValue];
        require(mesh.material.shaderType <= 2 && mesh.material.detailFunction <= 2 &&
                mesh.material.microFunction <= 2, @"Unsupported environment detail function");
        float scales[6];
        for (int i = 0; i < 3; i++) {
            mesh.detail[i] = [m[@"detail_textures"][i] unsignedIntegerValue];
            require(mesh.detail[i] < textures.count, @"Invalid detail texture reference");
        }
        for (int i = 0; i < 6; i++) {
            scales[i] = [m[@"detail_scales"][i] floatValue];
            require(std::isfinite(scales[i]), @"Invalid detail texture scale");
        }
        mesh.material.detailScale01 = {scales[0], scales[1], scales[2], scales[3]};
        float alphaScale[2] = {1, 1};
        if (m[@"alpha_test_scale"]) {
            require([m[@"alpha_test_scale"] count] == 2, @"Invalid alpha test scale");
            for (int i = 0; i < 2; i++) alphaScale[i] = finiteNumber(m[@"alpha_test_scale"][i], @"Invalid alpha test scale");
        }
        mesh.material.detailScale2 = {scales[4], scales[5], alphaScale[0], alphaScale[1]};
        require(mesh.first <= idx.length / 4 && mesh.count <= idx.length / 4 - mesh.first &&
                mesh.count % 3 == 0 && mesh.base < textures.count && mesh.lightmap < textures.count && mesh.alphaMap < textures.count,
                @"Invalid mesh range or texture reference");
        meshes.push_back(mesh);
        opaqueTriangleCount += mesh.count / 3;
    }
    for (NSDictionary *m in manifest[@"sky_meshes"]) {
        require([m[@"textures"] count] == 3 && [m[@"scales"] count] == 6, @"Invalid sky material");
        SkyMesh mesh = {};
        mesh.first = [m[@"first_index"] unsignedIntegerValue]; mesh.count = [m[@"index_count"] unsignedIntegerValue];
        mesh.material.kind = [m[@"kind"] unsignedIntValue];
        require(mesh.material.kind >= 1 && mesh.material.kind <= 3 && mesh.count % 3 == 0 &&
                mesh.first <= idx.length / 4 && mesh.count <= idx.length / 4 - mesh.first, @"Invalid sky mesh range or kind");
        float scale[6];
        for (NSUInteger i = 0; i < 3; i++) {
            mesh.textures[i] = [m[@"textures"][i] unsignedIntegerValue];
            require(mesh.textures[i] < textures.count, @"Invalid sky texture reference");
        }
        for (NSUInteger i = 0; i < 6; i++) scale[i] = finiteNumber(m[@"scales"][i], @"Invalid sky texture scale");
        mesh.material.scale01 = {scale[0], scale[1], scale[2], scale[3]};
        mesh.material.scale2 = {scale[4], scale[5], 0, 0};
        skyMeshes.push_back(mesh);
        skyTriangleCount += mesh.count / 3;
    }
    for (NSDictionary *m in manifest[@"decal_meshes"]) {
        DecalMesh mesh = {};
        mesh.first = [m[@"first_index"] unsignedIntegerValue]; mesh.count = [m[@"index_count"] unsignedIntegerValue];
        mesh.texture = [m[@"base_texture"] unsignedIntegerValue];
        mesh.tintIntensity = float4Array(m[@"tint_intensity"], @"Invalid decal tint or intensity");
        for (NSUInteger i = 0; i < 4; i++) require(mesh.tintIntensity[i] >= 0 && mesh.tintIntensity[i] <= 1, @"Invalid decal tint or intensity");
        require(mesh.count % 3 == 0 && mesh.first <= idx.length / 4 && mesh.count <= idx.length / 4 - mesh.first &&
                mesh.texture < textures.count && [m[@"framebuffer_blend"] isEqualToString:@"add_one_one"],
                @"Invalid decal mesh range or blend");
        decalMeshes.push_back(mesh);
        decalTriangleCount += mesh.count / 3;
    }
    for (NSDictionary *m in manifest[@"teleporter_meshes"]) {
        if ([m[@"kind"] unsignedIntValue] == 0) continue;
        TeleporterMesh mesh = {};
        mesh.first = [m[@"first_index"] unsignedIntegerValue]; mesh.count = [m[@"index_count"] unsignedIntegerValue];
        mesh.placement = [m[@"placement_index"] unsignedIntegerValue];
        mesh.material.kind = [m[@"kind"] unsignedIntValue];
        NSUInteger mapCount = mesh.material.kind == 1 ? 4 : 3;
        require((mesh.material.kind == 1 || mesh.material.kind == 2) && [m[@"textures"] count] == 4 &&
                [m[@"maps"] count] == mapCount && [m[@"constant_colors"] count] == 2 &&
                [m[@"blend"] isEqualToString:@"add"] && [m[@"fade_mode"] intValue] == 2 &&
                mesh.count % 3 == 0 && mesh.first <= idx.length / 4 && mesh.count <= idx.length / 4 - mesh.first,
                @"Invalid teleporter mesh, maps or blend");
        for (NSUInteger i = 0; i < 4; i++) {
            mesh.textures[i] = [m[@"textures"][i] unsignedIntegerValue];
            require(mesh.textures[i] < textures.count, @"Invalid teleporter texture reference");
            mesh.material.scaleOffset[i] = {1, 1, 0, 0};
        }
        for (NSUInteger i = 0; i < mapCount; i++) {
            NSDictionary *map = m[@"maps"][i];
            mesh.material.scaleOffset[i] = float4Array(map[@"scale_offset"], @"Invalid teleporter map transform");
            mesh.material.uAnimation[i] = float4Array(map[@"u_animation"], @"Invalid teleporter U animation");
            mesh.material.vAnimation[i] = float4Array(map[@"v_animation"], @"Invalid teleporter V animation");
            mesh.material.rAnimation[i] = float4Array(map[@"r_animation"], @"Invalid teleporter rotation animation");
            mesh.material.rotationCenter[i] = float4Array(map[@"rotation_center"], @"Invalid teleporter rotation center");
            for (simd_float4 animation : {mesh.material.uAnimation[i], mesh.material.vAnimation[i], mesh.material.rAnimation[i]})
                require(animation.x == 0 || animation.x == 6, @"Unsupported teleporter animation function");
        }
        for (NSUInteger i = 0; i < 2; i++) mesh.material.constantColor[i] = float4Array(m[@"constant_colors"][i], @"Invalid teleporter constant color");
        teleporterMeshes.push_back(mesh);
        teleporterTriangleCount += mesh.count / 3;
    }
    for (NSDictionary *m in manifest[@"transparent_bsp_meshes"]) {
        require([m isKindOfClass:NSDictionary.class], @"Invalid transparent BSP mesh description");
        TransparentBspMesh mesh = {};
        mesh.first = [m[@"first_index"] unsignedIntegerValue]; mesh.count = [m[@"index_count"] unsignedIntegerValue];
        mesh.material.kind = [m[@"kind"] unsignedIntValue];
        mesh.material.pad[0] = [m[@"fade_mode"] unsignedIntValue];
        mesh.twoSided = [m[@"two_sided"] boolValue]; mesh.isDecal = [m[@"is_decal"] boolValue];
        mesh.material.pad[1] = mesh.isDecal ? 1u : 0u;
        NSUInteger mapCount = mesh.material.kind == 1 ? 4 : 1;
        require((mesh.material.kind == 1 || mesh.material.kind == 3) && [m[@"textures"] count] == 4 &&
                [m[@"maps"] count] == mapCount && [m[@"constant_colors"] count] == 2 &&
                [m[@"blend"] isEqualToString:@"add"] && m[@"fade_mode"] && mesh.material.pad[0] <= 2 &&
                m[@"two_sided"] && m[@"is_decal"] && m[@"alpha_test"] && ![m[@"alpha_test"] boolValue] &&
                mesh.count && mesh.count % 3 == 0 && mesh.first <= idx.length / 4 &&
                mesh.count <= idx.length / 4 - mesh.first, @"Invalid transparent BSP mesh, maps or state");
        for (NSUInteger i = 0; i < 4; i++) {
            mesh.textures[i] = [m[@"textures"][i] unsignedIntegerValue];
            require(mesh.textures[i] < textures.count, @"Invalid transparent BSP texture reference");
            mesh.material.scaleOffset[i] = {1, 1, 0, 0};
        }
        for (NSUInteger i = 0; i < mapCount; i++) {
            NSDictionary *map = m[@"maps"][i];
            mesh.material.scaleOffset[i] = float4Array(map[@"scale_offset"], @"Invalid transparent BSP map transform");
            mesh.material.uAnimation[i] = float4Array(map[@"u_animation"], @"Invalid transparent BSP U animation");
            mesh.material.vAnimation[i] = float4Array(map[@"v_animation"], @"Invalid transparent BSP V animation");
            mesh.material.rAnimation[i] = float4Array(map[@"r_animation"], @"Invalid transparent BSP rotation animation");
            mesh.material.rotationCenter[i] = float4Array(map[@"rotation_center"], @"Invalid transparent BSP rotation center");
            for (simd_float4 animation : {mesh.material.uAnimation[i], mesh.material.vAnimation[i], mesh.material.rAnimation[i]})
                require(animation.x == 0 || animation.x == 6, @"Unsupported transparent BSP animation function");
        }
        for (NSUInteger i = 0; i < 2; i++)
            mesh.material.constantColor[i] = float4Array(m[@"constant_colors"][i], @"Invalid transparent BSP constant color");
        transparentBspMeshes.push_back(mesh);
        transparentBspTriangleCount += mesh.count / 3;
    }
    if (!teleporterMeshes.empty() || !transparentBspMeshes.empty()) {
        NSData *normalData = readFile([scene stringByAppendingPathComponent:@"teleporter_normals.bin"]);
        require(normalData.length == v.length / sizeof(Vertex) * 12, @"Invalid teleporter normal buffer size");
        const float *normal = (const float *)normalData.bytes;
        for (NSUInteger i = 0; i < normalData.length / 4; i++) require(std::isfinite(normal[i]), @"Invalid teleporter normal");
        teleporterNormals = [device newBufferWithBytes:normalData.bytes length:normalData.length options:MTLResourceStorageModeShared];
        require(teleporterNormals != nil, @"Teleporter normal buffer allocation failed");
    }
    triangleCount = opaqueTriangleCount + skyTriangleCount + decalTriangleCount + teleporterTriangleCount + transparentBspTriangleCount;
    NSArray *camera = manifest[@"camera"];
    require(camera.count == 4, @"Invalid camera");
    initialPosition = (simd_float3){[camera[0] floatValue], [camera[1] floatValue], [camera[2] floatValue]};
    initialYaw = [camera[3] floatValue];
    exposure = 1;
    verticalFov = 65;
    captureWidth = 1280; captureHeight = 720;
    startTime = CACurrentMediaTime();
    mapName = manifest[@"map"];
    [self resetCamera];
    fprintf(stdout, "Direct Metal on %s: %s, %zu opaque + %zu sky + %zu decal + %zu transparent BSP + %zu teleporter draws, %lu triangles, %lu textures, %lu authored mip levels\n",
            device.name.UTF8String, mapName.UTF8String, meshes.size(), skyMeshes.size(), decalMeshes.size(), transparentBspMeshes.size(), teleporterMeshes.size(),
            triangleCount, textures.count, textureMipLevelCount);
    fflush(stdout);
    return self;
}
- (void)resetCamera { position = initialPosition; yaw = initialYaw; pitch = 0; }
- (void)inspectTeleporter {
    if (![mapName isEqualToString:@"bloodgulch"] || !teleporterPlacementCount) return;
    position = (simd_float3){82.83385f, -117.65f, 1.45f};
    yaw = (float)M_PI_2; pitch = 0;
}
- (void)encode:(id<MTLCommandBuffer>)command pass:(MTLRenderPassDescriptor *)pass size:(CGSize)size {
    float aspect = size.width / std::max(1.0, size.height);
    Uniforms uniforms = {cameraMatrix(position, yaw, pitch, aspect, verticalFov), mode, exposure, {0, 0}};
    simd_float3 forward = {cosf(yaw) * cosf(pitch), sinf(yaw) * cosf(pitch), sinf(pitch)};
    AtmosphericFogUniforms fog = {{0, 0, 0, 0}, {fogColor.x, fogColor.y, fogColor.z, fogDensity}};
    if (fogEnabled) {
        float inverseRange = 1.0f / (fogEnd - fogStart);
        fog.coordinatePlane = {forward.x * inverseRange, forward.y * inverseRange, forward.z * inverseRange,
                               -(fogStart + simd_dot(position, forward)) * inverseRange};
    }
    float seconds = (float)(fixedAnimationTime ? animationTime : CACurrentMediaTime() - startTime);
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    require(encoder != nil, @"Could not create render encoder");
    encoder.label = @"Static authored world / sky / decals / BSP lights / teleporters";
    [encoder setCullMode:MTLCullModeNone];
    [encoder setTriangleFillMode:wireframe ? MTLTriangleFillModeLines : MTLTriangleFillModeFill];
    [encoder setVertexBuffer:vertices offset:0 atIndex:0];
    if (!skyMeshes.empty()) {
        SkyFrameUniforms sky = {cameraMatrix(position, yaw, pitch, aspect, verticalFov, 1.0f / 256.0f, 1024.0f),
                               {position.x, position.y, position.z, exposure}, {1, 1, 1, 0}};
        [encoder setRenderPipelineState:skyPipeline];
        [encoder setDepthStencilState:skyDepthState];
        [encoder setVertexBytes:&sky length:sizeof(sky) atIndex:1];
        [encoder setFragmentBytes:&sky length:sizeof(sky) atIndex:0];
        for (const SkyMesh &m : skyMeshes) {
            for (NSUInteger i = 0; i < 3; i++) [encoder setFragmentTexture:textures[m.textures[i]] atIndex:i];
            [encoder setFragmentBytes:&m.material length:sizeof(m.material) atIndex:1];
            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
        }
    }
    [encoder setRenderPipelineState:pipeline];
    [encoder setDepthStencilState:depthState];
    // Original environment draws discard CCW faces. Sky and transparent
    // teleporter materials use their separate two-sided passes.
    [encoder setFrontFacingWinding:MTLWindingClockwise];
    [encoder setCullMode:MTLCullModeBack];
    [encoder setVertexBytes:&uniforms length:sizeof(uniforms) atIndex:1];
    [encoder setVertexBytes:&fog length:sizeof(fog) atIndex:2];
    [encoder setFragmentBytes:&uniforms length:sizeof(uniforms) atIndex:0];
    [encoder setFragmentBytes:&fog length:sizeof(fog) atIndex:2];
    [encoder setFragmentTexture:textures[fogDensityTexture] atIndex:5];
    for (const Mesh &m : meshes) {
        [encoder setFragmentTexture:textures[m.base] atIndex:0];
        [encoder setFragmentTexture:textures[m.lightmap] atIndex:1];
        for (int i = 0; i < 3; i++) [encoder setFragmentTexture:textures[m.detail[i]] atIndex:i + 2];
        [encoder setFragmentTexture:textures[m.alphaMap] atIndex:6];
        [encoder setFragmentBytes:&m.material length:sizeof(m.material) atIndex:1];
        [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                             indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
    }
    if (!decalMeshes.empty()) {
        // rasterizer_xbox_decals.c preserves clockwise fronts and discards
        // CCW backs, including projected permanent sign polygons.
        [encoder setFrontFacingWinding:MTLWindingClockwise];
        [encoder setCullMode:MTLCullModeBack];
        [encoder setRenderPipelineState:decalPipeline];
        [encoder setDepthStencilState:overlayDepthState];
        [encoder setDepthBias:-8 slopeScale:-2 clamp:0];
        [encoder setFragmentTexture:textures[fogDensityTexture] atIndex:1];
        for (const DecalMesh &m : decalMeshes) {
            [encoder setFragmentTexture:textures[m.texture] atIndex:0];
            [encoder setFragmentBytes:&m.tintIntensity length:sizeof(m.tintIntensity) atIndex:1];
            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
        }
        [encoder setDepthBias:0 slopeScale:0 clamp:0];
    }
    if (!transparentBspMeshes.empty()) {
        TeleporterFrameUniforms frame = {uniforms.viewProjection, {forward.x, forward.y, forward.z, exposure},
                                        fog.coordinatePlane, {fogRawDensity, seconds, 0, 0}};
        [encoder setRenderPipelineState:transparentBspPipeline];
        [encoder setDepthStencilState:overlayDepthState];
        [encoder setFrontFacingWinding:MTLWindingClockwise];
        [encoder setVertexBytes:&frame length:sizeof(frame) atIndex:1];
        [encoder setVertexBuffer:teleporterNormals offset:0 atIndex:2];
        [encoder setFragmentBytes:&frame length:sizeof(frame) atIndex:0];
        [encoder setFragmentBytes:&fog length:sizeof(fog) atIndex:2];
        [encoder setFragmentTexture:textures[fogDensityTexture] atIndex:4];
        for (const TransparentBspMesh &m : transparentBspMeshes) {
            [encoder setCullMode:m.twoSided ? MTLCullModeNone : MTLCullModeBack];
            [encoder setDepthBias:m.isDecal ? -8 : 0 slopeScale:m.isDecal ? -2 : 0 clamp:0];
            for (NSUInteger i = 0; i < 4; i++) [encoder setFragmentTexture:textures[m.textures[i]] atIndex:i];
            [encoder setVertexBytes:&m.material length:sizeof(m.material) atIndex:3];
            [encoder setFragmentBytes:&m.material length:sizeof(m.material) atIndex:1];
            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
        }
        [encoder setDepthBias:0 slopeScale:0 clamp:0];
    }
    if (!teleporterMeshes.empty()) {
        [encoder setCullMode:MTLCullModeNone];
        TeleporterFrameUniforms frame = {uniforms.viewProjection, {forward.x, forward.y, forward.z, exposure},
                                        fog.coordinatePlane, {fogRawDensity, seconds, 0, 0}};
        [encoder setRenderPipelineState:teleporterPipeline];
        [encoder setDepthStencilState:overlayDepthState];
        [encoder setVertexBytes:&frame length:sizeof(frame) atIndex:1];
        [encoder setVertexBuffer:teleporterNormals offset:0 atIndex:2];
        [encoder setFragmentBytes:&frame length:sizeof(frame) atIndex:0];
        for (const TeleporterMesh &m : teleporterMeshes) {
            for (NSUInteger i = 0; i < 4; i++) [encoder setFragmentTexture:textures[m.textures[i]] atIndex:i];
            [encoder setVertexBytes:&m.material length:sizeof(m.material) atIndex:3];
            [encoder setFragmentBytes:&m.material length:sizeof(m.material) atIndex:1];
            [encoder drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:m.count
                                 indexType:MTLIndexTypeUInt32 indexBuffer:indices indexBufferOffset:m.first * 4];
        }
    }
    [encoder endEncoding];
}
- (void)drawInMTKView:(MTKView *)view {
    double start = CACurrentMediaTime();
    float dt = lastTime ? std::min(0.1, start - lastTime) : 0;
    lastTime = start;
    simd_float3 forward = {cosf(yaw) * cosf(pitch), sinf(yaw) * cosf(pitch), sinf(pitch)};
    simd_float3 right = {sinf(yaw), -cosf(yaw), 0};
    float speed = dt * ((NSEvent.modifierFlags & NSEventModifierFlagShift) ? 24 : 8);
    position += speed * ((keys[13] - keys[1]) * forward + (keys[2] - keys[0]) * right);
    position.z += speed * (keys[14] - keys[12]); // E / Q
    id<CAMetalDrawable> drawable = view.currentDrawable;
    MTLRenderPassDescriptor *pass = view.currentRenderPassDescriptor;
    if (!drawable || !pass) return;
    id<MTLCommandBuffer> command = [queue commandBuffer];
    [self encode:command pass:pass size:view.drawableSize];
    [command presentDrawable:drawable];
    // One frame in flight is sufficient for this inspectable POC.
    [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted,
            command.error.localizedDescription ?: @"Metal rendering failed");
    frames++;
    double gpu = (command.GPUEndTime - command.GPUStartTime) * 1000;
    if (frames % 30 == 0) {
        NSArray *modes = @[@"Xbox diffuse detail × baked lightmap", @"Base texture", @"Baked lightmap", @"Xbox diffuse detail"];
        help.stringValue = [NSString stringWithFormat:
            @"%@ · DIRECT METAL POC\n%@%@ · GPU %.2f ms\nDrag to look · WASD move · Q/E down/up · Shift faster\n1–4 shading · Tab wire · T portal · R reset · F5 capture\nStatic world, sky, signs, teleporters · simplified lighting",
            mapName, modes[mode], wireframe ? @" · Wireframe" : @"", gpu];
    }
}
- (void)mtkView:(MTKView *)view drawableSizeWillChange:(CGSize)size { (void)view; (void)size; }
- (void)capture:(NSString *)path frames:(NSUInteger)count {
    const NSUInteger width = captureWidth, height = captureHeight;
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
        width:width height:height mipmapped:NO];
    td.storageMode = MTLStorageModeShared; td.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> color = [device newTextureWithDescriptor:td];
    td.pixelFormat = MTLPixelFormatDepth32Float; td.storageMode = MTLStorageModePrivate;
    id<MTLTexture> depth = [device newTextureWithDescriptor:td];
    require(color && depth, @"Offscreen render target allocation failed");
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = color;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(clearColorRGB.x, clearColorRGB.y, clearColorRGB.z, 1);
    pass.depthAttachment.texture = depth;
    pass.depthAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = MTLStoreActionDontCare;
    pass.depthAttachment.clearDepth = 1;
    double cpu = 0, gpu = 0;
    for (NSUInteger i = 0; i < count + 10; i++) {
        @autoreleasepool {
            double start = CACurrentMediaTime();
            id<MTLCommandBuffer> command = [queue commandBuffer];
            [self encode:command pass:pass size:CGSizeMake(width, height)];
            [command commit];
            double submitted = CACurrentMediaTime();
            [command waitUntilCompleted];
            require(command.status == MTLCommandBufferStatusCompleted,
                    command.error.localizedDescription ?: @"Offscreen rendering failed");
            if (i >= 10) {
                cpu += (submitted - start) * 1000;
                gpu += (command.GPUEndTime - command.GPUStartTime) * 1000;
            }
        }
    }
    std::vector<uint8_t> bytes(width * height * 4);
    [color getBytes:bytes.data() bytesPerRow:width * 4 fromRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0];
    NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc] initWithBitmapDataPlanes:nil pixelsWide:width
        pixelsHigh:height bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO
        colorSpaceName:NSDeviceRGBColorSpace bytesPerRow:width * 4 bitsPerPixel:32];
    for (NSUInteger i = 0; i < width * height; i++) {
        bitmap.bitmapData[i * 4] = bytes[i * 4 + 2];
        bitmap.bitmapData[i * 4 + 1] = bytes[i * 4 + 1];
        bitmap.bitmapData[i * 4 + 2] = bytes[i * 4];
        bitmap.bitmapData[i * 4 + 3] = 255;
    }
    NSData *png = [bitmap representationUsingType:NSBitmapImageFileTypePNG properties:@{}];
    require([png writeToFile:path atomically:YES], @"Could not save capture");
    NSDictionary *metrics = @{@"backend": @"direct-metal", @"device": device.name, @"map": mapName,
        @"width": @(width), @"height": @(height), @"sample_frames": @(count), @"warmup_frames": @10,
        @"draws": @(meshes.size() + skyMeshes.size() + decalMeshes.size() + transparentBspMeshes.size() + teleporterMeshes.size()),
        @"triangles": @(triangleCount), @"bsp_triangles": @(bspTriangleCount),
        @"passes": @{
            @"opaque": @{@"draws": @(meshes.size()), @"triangles": @(opaqueTriangleCount)},
            @"sky": @{@"draws": @(skyMeshes.size()), @"triangles": @(skyTriangleCount)},
            @"decals": @{@"draws": @(decalMeshes.size()), @"triangles": @(decalTriangleCount)},
            @"transparent_bsp": @{@"draws": @(transparentBspMeshes.size()), @"triangles": @(transparentBspTriangleCount)},
            @"teleporter_transparency": @{@"draws": @(teleporterMeshes.size()), @"triangles": @(teleporterTriangleCount)}},
        @"teleporter_placements": @(teleporterPlacementCount), @"permanent_decals": @(decalMeshes.size()),
        @"textures": @(textures.count), @"texture_mip_levels": @(textureMipLevelCount),
        @"native_bc1_textures": @(compressedTextureCount),
        @"texture_mip_source": @"Authored cache levels; original BC1 blocks where available; no generated mipmaps",
        @"source_sha256": sourceSHA256 ?: @"", @"scene_sha256": sceneSHA256, @"shader_sha256": shaderSHA256,
        @"shader_sources_sha256": shaderSourcesSHA256,
        @"host_sha256": hostSHA256,
        @"raster_state": @{@"fragment_sample_mask": @"all_samples",
                            @"opaque_front_winding": @"clockwise", @"opaque_cull": @"back",
                            @"opaque_depth_compare": @"less_equal", @"opaque_depth_write": @YES,
                            @"decal_depth_compare": @"less_equal", @"decal_depth_write": @NO,
                            @"decal_front_winding": @"clockwise", @"decal_cull": @"back",
                            @"decal_depth_bias": @-8, @"decal_slope_scale": @-2,
                            @"transparent_bsp_blend": @"add_one_one_rgb", @"transparent_bsp_depth_compare": @"less_equal",
                            @"transparent_bsp_depth_write": @NO, @"transparent_bsp_cull": @"back_except_authored_two_sided",
                            @"transparent_bsp_bias": @"-8/-2_only_authored_is_decal"},
        @"camera_position": @[@(position.x), @(position.y), @(position.z)],
        @"camera_yaw": @(yaw), @"camera_pitch": @(pitch), @"vertical_fov_degrees": @(verticalFov),
        @"shading_mode": @(mode), @"exposure": @(exposure), @"wireframe": @(wireframe),
        @"clip_ranges": @{@"world": @{@"near": @0.0625, @"far": @1024},
                           @"sky": @{@"near": @(1.0 / 256.0), @"far": @1024}},
        @"animation_seconds": @(animationTime),
        @"clear_color": @[@(clearColorRGB.x), @(clearColorRGB.y), @(clearColorRGB.z)],
        @"atmospheric_fog": @{@"enabled": @(fogEnabled), @"color": @[@(fogColor.x), @(fogColor.y), @(fogColor.z)],
                              @"maximum_density": @(fogDensity), @"start": @(fogStart), @"end": @(fogEnd),
                              @"lookup_texture": @(fogDensityTexture), @"planar_mode": @0},
        @"cpu_encode_submit_ms": @(cpu / count), @"gpu_ms": @(gpu / count),
        @"scope": @"Static authored opaque/transparent BSP, sky, permanent signs and teleporter scenery; not a full gameplay frame",
        @"limitations": @[@"Simplified baked/object lighting; bump/specular and original multipass framebuffer rounding incomplete",
                           @"Sky texture animation omitted; teleporter animations use original periodic slide lookup",
                           @"No gameplay, HUD, dynamic actors, weapon, water or full visibility culling",
                           @"Original stencil masks for dynamic/first-person passes omitted in this static scene"]};
    NSData *json = [NSJSONSerialization dataWithJSONObject:metrics options:NSJSONWritingPrettyPrinted error:nil];
    require([json writeToFile:[path stringByAppendingString:@".json"] atomically:YES], @"Could not save metrics");
    printf("Capture: %s\n%s\n", path.UTF8String, [[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
}
@end

@interface SceneView : MTKView
@property(nonatomic, strong) SceneRenderer *renderer;
@end
@implementation SceneView
- (BOOL)acceptsFirstResponder { return YES; }
- (BOOL)resignFirstResponder { memset(_renderer->keys, 0, sizeof(_renderer->keys)); return YES; }
- (void)keyDown:(NSEvent *)event {
    unsigned short key = event.keyCode;
    if (key < 128) _renderer->keys[key] = true;
    if (event.isARepeat) return;
    if (key == 15) [_renderer resetCamera];
    if (key == 17) [_renderer inspectTeleporter];
    if (key == 48) _renderer->wireframe = !_renderer->wireframe;
    if (key == 18) _renderer->mode = 0;
    if (key == 19) _renderer->mode = 1;
    if (key == 20) _renderer->mode = 2;
    if (key == 21) _renderer->mode = 3;
    if (key == 33) _renderer->exposure = std::max(0.1f, _renderer->exposure / 1.2f);
    if (key == 30) _renderer->exposure = std::min(8.0f, _renderer->exposure * 1.2f);
    if (key == 96) {
        // Save the current pose and drawable dimensions so an intermittent
        // edge artifact can be replayed through the original renderer.
        NSString *folder = [NSBundle.mainBundle.bundlePath.stringByDeletingLastPathComponent
                            stringByAppendingPathComponent:@"captures"];
        NSError *error = nil;
        if (![[NSFileManager defaultManager] createDirectoryAtPath:folder
                withIntermediateDirectories:YES attributes:nil error:&error]) {
            fprintf(stderr, "Could not create capture directory: %s\n", error.localizedDescription.UTF8String);
            return;
        }
        NSString *path = [folder stringByAppendingPathComponent:
                         [NSString stringWithFormat:@"camera-%@.png", NSUUID.UUID.UUIDString]];
        NSUInteger savedWidth = _renderer->captureWidth, savedHeight = _renderer->captureHeight;
        bool savedFixedTime = _renderer->fixedAnimationTime;
        double savedTime = _renderer->animationTime;
        _renderer->captureWidth = (NSUInteger)std::clamp(self.drawableSize.width, 1.0, 8192.0);
        _renderer->captureHeight = (NSUInteger)std::clamp(self.drawableSize.height, 1.0, 8192.0);
        if (!savedFixedTime) _renderer->animationTime = CACurrentMediaTime() - _renderer->startTime;
        _renderer->fixedAnimationTime = true;
        [_renderer capture:path frames:1];
        _renderer->captureWidth = savedWidth; _renderer->captureHeight = savedHeight;
        _renderer->fixedAnimationTime = savedFixedTime; _renderer->animationTime = savedTime;
    }
    if (key == 53) [[NSApplication sharedApplication] terminate:nil];
}
- (void)keyUp:(NSEvent *)event { if (event.keyCode < 128) _renderer->keys[event.keyCode] = false; }
- (void)mouseDown:(NSEvent *)event { [self.window makeFirstResponder:self]; }
- (void)mouseDragged:(NSEvent *)event {
    _renderer->yaw -= event.deltaX * 0.004f;
    _renderer->pitch = std::clamp(_renderer->pitch - (float)event.deltaY * 0.004f, -1.5f, 1.5f);
}
- (void)rightMouseDragged:(NSEvent *)event { [self mouseDragged:event]; }
- (void)scrollWheel:(NSEvent *)event { _renderer->position.z += event.scrollingDeltaY * 0.08f; }
@end

@interface AppDelegate : NSObject<NSApplicationDelegate, NSWindowDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) SceneRenderer *renderer;
@end
@implementation AppDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    NSRect rect = NSMakeRect(0, 0, 1280, 800);
    self.window = [[NSWindow alloc] initWithContentRect:rect
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
        backing:NSBackingStoreBuffered defer:NO];
    NSDictionary *mapTitles = @{@"bloodgulch": @"Blood Gulch", @"beavercreek": @"Battle Creek",
                                @"hangemhigh": @"Hang ’Em High", @"sidewinder": @"Sidewinder"};
    NSString *mapTitle = mapTitles[self.renderer->mapName] ?: self.renderer->mapName;
    NSString *previewVersion = [NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleShortVersionString"] ?: @"0.6";
    self.window.title = [NSString stringWithFormat:@"Halo Metal POC %@ — %@ scene viewer", previewVersion, mapTitle];
    self.window.delegate = self;
    SceneView *view = [[SceneView alloc] initWithFrame:rect device:self.renderer->device];
    view.renderer = self.renderer; view.delegate = self.renderer;
    view.colorPixelFormat = MTLPixelFormatBGRA8Unorm;
    view.depthStencilPixelFormat = MTLPixelFormatDepth32Float;
    simd_float3 clear = self.renderer->clearColorRGB;
    view.clearColor = MTLClearColorMake(clear.x, clear.y, clear.z, 1);
    view.preferredFramesPerSecond = 60;
    view.autoresizingMask = NSViewWidthSizable | NSViewHeightSizable;
    self.window.contentView = view;
    NSTextField *label = [NSTextField labelWithString:@"Direct Metal · loading scene…"];
    label.frame = NSMakeRect(16, rect.size.height - 126, 490, 110);
    label.font = [NSFont monospacedSystemFontOfSize:12 weight:NSFontWeightRegular];
    label.textColor = NSColor.whiteColor;
    label.backgroundColor = [NSColor colorWithWhite:0.06 alpha:0.86];
    label.drawsBackground = YES;
    label.autoresizingMask = NSViewMinYMargin;
    self.renderer->help = label;
    [view addSubview:label];
    [self.window center]; [self.window makeKeyAndOrderFront:nil];
    [self.window makeFirstResponder:view];
    [NSApp activateIgnoringOtherApps:YES];
}
- (void)windowDidResignKey:(NSNotification *)note { memset(self.renderer->keys, 0, sizeof(self.renderer->keys)); }
- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)app { return YES; }
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *resources = NSBundle.mainBundle.resourcePath;
        NSString *scene = [resources stringByAppendingPathComponent:@"scene"];
        NSString *shader = [resources stringByAppendingPathComponent:@"Scene.metal"];
        NSString *capture = nil;
        NSUInteger frames = 60;
        NSUInteger width = 1280, height = 720;
        float verticalFov = 65;
        double animationSeconds = 0;
        bool timeSpecified = false;
        bool overview = false;
        bool teleporter = false;
        bool cameraSpecified = false;
        float camera[5] = {};
        for (int i = 1; i < argc; i++) {
            NSString *arg = @(argv[i]);
            if ([arg isEqualToString:@"--overview"]) overview = true;
            else if ([arg isEqualToString:@"--teleporter"]) teleporter = true;
            else if ([arg isEqualToString:@"--camera"] && i + 5 < argc) {
                require(!cameraSpecified, @"Camera may only be specified once");
                for (float &component : camera) {
                    char *end = nullptr;
                    const char *value = argv[++i];
                    component = strtof(value, &end);
                    require(end != value && *end == '\0' && std::isfinite(component) &&
                            std::abs(component) <= 1000000, @"Invalid camera position or angle");
                }
                require(std::abs(camera[4]) <= M_PI_2, @"Camera pitch must be within +/- pi/2 radians");
                cameraSpecified = true;
            }
            else if ([arg isEqualToString:@"--scene"] && i + 1 < argc) scene = @(argv[++i]);
            else if ([arg isEqualToString:@"--shader"] && i + 1 < argc) shader = @(argv[++i]);
            else if ([arg isEqualToString:@"--capture"] && i + 1 < argc) capture = @(argv[++i]);
            else if ([arg isEqualToString:@"--frames"] && i + 1 < argc)
                frames = parseInteger(argv[++i], 10000, @"Frames must be between 1 and 10000");
            else if ([arg isEqualToString:@"--width"] && i + 1 < argc)
                width = parseInteger(argv[++i], 8192, @"Capture width must be between 1 and 8192");
            else if ([arg isEqualToString:@"--height"] && i + 1 < argc)
                height = parseInteger(argv[++i], 8192, @"Capture height must be between 1 and 8192");
            else if ([arg isEqualToString:@"--vertical-fov"] && i + 1 < argc) verticalFov = parseVerticalFov(argv[++i]);
            else if ([arg isEqualToString:@"--time"] && i + 1 < argc) {
                char *end = nullptr;
                const char *value = argv[++i];
                animationSeconds = strtod(value, &end);
                require(end != value && *end == '\0' && std::isfinite(animationSeconds) &&
                        animationSeconds >= 0 && animationSeconds <= 1000000, @"Animation time must be between 0 and 1000000 seconds");
                timeSpecified = true;
            }
            else { fprintf(stderr, "Usage: HaloMetalPOC [--scene DIR] [--shader FILE] [--capture PNG] [--frames N] [--overview | --teleporter | --camera X Y Z YAW PITCH] [--width N] [--height N] [--vertical-fov DEGREES] [--time SECONDS]\nCamera angles are radians.\n"); return 2; }
        }
        require((int)overview + (int)teleporter + (int)cameraSpecified <= 1, @"Choose one camera preset or explicit camera");
        require(frames > 0 && frames <= 10000, @"Frames must be between 1 and 10000");
        SceneRenderer *renderer = [[SceneRenderer alloc] initWithScene:scene shader:shader];
        renderer->captureWidth = width; renderer->captureHeight = height; renderer->verticalFov = verticalFov;
        renderer->animationTime = animationSeconds;
        renderer->fixedAnimationTime = timeSpecified || capture != nil;
        if (overview) { renderer->position = (simd_float3){120, -182, 55}; renderer->yaw = 2.18; renderer->pitch = -0.50; }
        if (teleporter) [renderer inspectTeleporter];
        if (cameraSpecified) {
            renderer->position = (simd_float3){camera[0], camera[1], camera[2]};
            renderer->yaw = camera[3]; renderer->pitch = camera[4];
        }
        if (capture) { [renderer capture:capture frames:frames]; return 0; }
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        NSMenu *menu = [NSMenu new];
        NSMenuItem *item = [NSMenuItem new]; [menu addItem:item];
        NSMenu *appMenu = [NSMenu new]; item.submenu = appMenu;
        [appMenu addItemWithTitle:@"Quit Halo Metal POC" action:@selector(terminate:) keyEquivalent:@"q"];
        NSApp.mainMenu = menu;
        AppDelegate *delegate = [AppDelegate new]; delegate.renderer = renderer; NSApp.delegate = delegate;
        [NSApp run];
    }
    return 0;
}
