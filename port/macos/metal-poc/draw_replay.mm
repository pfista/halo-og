// Replay captured Xbox declarations, resources and NV2A-generated MSL.
// No game, static scene shader, OpenGL or ANGLE is linked into this executable.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <simd/simd.h>
#include <CommonCrypto/CommonDigest.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <vector>

struct VertexUniforms {
    simd_float4 c[192], viewportScale, viewportOffset;
    float pointSize, screenOffset, padding[2];
};
struct PixelUniforms {
    simd_float4 c0[8], c1[8], finalC0, finalC1, fogColor, fogParameters;
    float alphaReference, padding[3];
    simd_float4 bumpMatrix[4], bumpLuminance[4], textureScale[4], textureBorderColor[4], textureLodBias;
};
struct Inputs { simd_float4 v[16]; };
static_assert(sizeof(VertexUniforms) == 3120 && sizeof(PixelUniforms) == 608, "Generated shader uniform ABI");
static_assert(sizeof(Inputs) == 256, "Expanded Xbox attribute ABI");

static void require(bool value, NSString *reason) {
    if (!value) { fprintf(stderr, "metal-draw-replay: %s\n", reason.UTF8String); exit(1); }
}
static NSData *readFile(NSString *path) {
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
    require(data != nil, error.localizedDescription ?: path);
    return data;
}
static NSString *sha256(NSData *data) {
    require(data.length <= UINT32_MAX, @"Resource too large to hash");
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, bytes);
    NSMutableString *result = [NSMutableString new];
    for (unsigned char byte : bytes) [result appendFormat:@"%02x", byte];
    return result;
}
static double number(id value, double minimum, double maximum, bool integral, NSString *label) {
    require([value isKindOfClass:NSNumber.class], label);
    double n = [value doubleValue];
    require(std::isfinite(n) && n >= minimum && n <= maximum && (!integral || floor(n) == n), label);
    return n;
}
static NSUInteger integer(id value, NSUInteger maximum, NSString *label) {
    return (NSUInteger)number(value, 0, (double)maximum, true, label);
}
static bool boolean(id value, NSString *label) { return number(value, 0, 1, true, label) != 0; }
static simd_float4 vector4(id value, NSString *label) {
    require([value isKindOfClass:NSArray.class] && [value count] == 4, label);
    simd_float4 result;
    for (NSUInteger i = 0; i < 4; i++) result[i] = (float)number(value[i], -FLT_MAX, FLT_MAX, false, label);
    return result;
}
static void finiteFloats(NSData *data, NSString *label) {
    require(data.length % sizeof(float) == 0, label);
    const float *values = (const float *)data.bytes;
    for (NSUInteger i = 0; i < data.length / sizeof(float); i++) require(std::isfinite(values[i]), label);
}

struct Resources {
    NSString *root;
    NSMutableDictionary<NSString *, NSString *> *hashes;
    NSData *load(NSDictionary *description) {
        require([description isKindOfClass:NSDictionary.class], @"Missing resource descriptor");
        NSString *file = description[@"file"], *expected = description[@"sha256"];
        require([file isKindOfClass:NSString.class] && file.length && !file.isAbsolutePath &&
                ![file.pathComponents containsObject:@".."], @"Resource path escapes package");
        NSString *path = [[root stringByAppendingPathComponent:file] stringByResolvingSymlinksInPath];
        require([path hasPrefix:[root stringByAppendingString:@"/"]], @"Resource symlink escapes package");
        require([expected isKindOfClass:NSString.class] && expected.length == 64, @"Missing resource SHA256");
        NSData *data = readFile(path);
        require([sha256(data) isEqualToString:expected], [NSString stringWithFormat:@"Resource hash mismatch: %@", file]);
        if (description[@"size"]) require(data.length == integer(description[@"size"], UINT32_MAX, @"Invalid resource size"),
                                           @"Resource size mismatch");
        hashes[path] = expected;
        return data;
    }
    void unchanged() {
        for (NSString *path in hashes) require([sha256(readFile(path)) isEqualToString:hashes[path]],
                                               @"Replay resource changed during execution");
    }
};

static bool vertexFastMath(Resources &resources, NSDictionary *description) {
    NSDictionary *contract = description[@"compile_options"];
    if (!contract) {
        require(!description[@"compiler_evidence"] && !description[@"compiler_baseline"], @"Compiler evidence needs an explicit contract");
        return false;
    }
    require([description[@"entry"] isEqualToString:@"xgpu_vertex"] &&
            [contract isKindOfClass:NSDictionary.class] && contract.count == 5 &&
            [contract[@"contract"] isEqualToString:@"angle_metal_invariant_fast_v1"] &&
            boolean(contract[@"fast_math"], @"Invalid fast math contract") &&
            boolean(contract[@"preserve_invariance"], @"Invalid vertex invariance contract") &&
            [contract[@"math_mode"] isEqualToString:@"fast"] &&
            [contract[@"floating_point_functions"] isEqualToString:@"fast"], @"Unsupported shader compiler contract");
    NSDictionary *evidence = [NSJSONSerialization JSONObjectWithData:resources.load(description[@"compiler_evidence"])
                                                            options:0 error:nil];
    require([evidence isKindOfClass:NSDictionary.class] &&
            [evidence[@"kind"] isEqualToString:@"angle_shader_evidence"] &&
            boolean(evidence[@"complete"], @"Incomplete compiler evidence") &&
            [evidence[@"source_revision"] isEqualToString:@"c053bf85793b"], @"Unknown original compiler evidence");
    NSDictionary *flags = evidence[@"evidence"][@"compiler_options_inferred_from_pinned_source"];
    require(!boolean(flags[@"disableFastMath"], @"Missing original fast math evidence") &&
            boolean(flags[@"usesInvariance_vertex"], @"Missing original vertex invariance evidence") &&
            boolean(flags[@"preserveInvariance_vertex"], @"Missing original compiler invariance evidence") &&
            boolean(flags[@"legacy_fastMathEnabled"], @"Missing original legacy compiler evidence") &&
            [flags[@"mathMode_ifSDK_andRuntimeMacOS15"] isEqualToString:@"Fast"] &&
            [flags[@"mathFloatingPointFunctions_ifSDK_andRuntimeMacOS15"] isEqualToString:@"Fast"], @"Compiler policy differs from supported original source");
    NSDictionary *pinned = @{
        @"ProgramMtl.mm": @"7d4eab2d9ec9c16ee0ba9acdae980aef3d0552095a2171a9025675add012149a",
        @"mtl_utils.mm": @"167da7b64935428bf0bdd59b04d765fb72acd4769ebbaab27d665fa70c303065"};
    for (NSString *name in pinned) {
        NSDictionary *source = evidence[@"source_files"][name];
        NSString *path = source[@"file"];
        require([path isKindOfClass:NSString.class] && path.isAbsolutePath &&
                [source[@"sha256"] isEqualToString:pinned[name]] &&
                [sha256(readFile(path)) isEqualToString:pinned[name]], @"Original compiler policy source is stale or unknown");
        resources.hashes[path] = pinned[name];
    }
    NSString *baseline = [[NSString alloc] initWithData:resources.load(description[@"compiler_baseline"]) encoding:NSUTF8StringEncoding];
    require(baseline && [baseline containsString:@"invariant gl_Position;"] &&
            ![baseline containsString:@"isnan"] && ![baseline containsString:@"isinf"], @"Original shader flags do not permit the fast vertex contract");
    return true;
}

static id<MTLLibrary> library(id<MTLDevice> device, Resources &resources, NSDictionary *description) {
    NSString *source = [[NSString alloc] initWithData:resources.load(description) encoding:NSUTF8StringEncoding];
    require(source != nil, @"Shader source is not UTF-8");
    bool fastMath = vertexFastMath(resources, description);
    MTLCompileOptions *options = [MTLCompileOptions new];
    options.fastMathEnabled = fastMath; options.preserveInvariance = YES;
    if (@available(macOS 15.0, *)) {
        options.mathMode = fastMath ? MTLMathModeFast : MTLMathModeSafe;
        options.mathFloatingPointFunctions = fastMath ? MTLMathFloatingPointFunctionsFast : MTLMathFloatingPointFunctionsPrecise;
    }
    NSError *error = nil;
    id<MTLLibrary> result = [device newLibraryWithSource:source options:options error:&error];
    require(result != nil, error.localizedDescription ?: @"Native shader compilation failed");
    return result;
}

// D3DVSDT values encode the Xbox fetch format, not PC D3D9 declarations.
// Component defaults and normalized endpoints match the source fetch contract.
static NSUInteger attributeBytes(unsigned type) {
    switch (type) {
    case 0x02: return 0; // NONE: fixed register value
    case 0x12: return 4; case 0x22: return 8; case 0x32: case 0x72: return 12; case 0x42: return 16;
    case 0x40: case 0x16: return 4;
    case 0x11: case 0x15: return 2; case 0x21: case 0x25: return 4;
    case 0x31: case 0x35: return 6; case 0x41: case 0x45: return 8;
    case 0x14: return 1; case 0x24: return 2; case 0x34: return 3; case 0x44: return 4;
    default: require(false, @"Unsupported Xbox vertex attribute format"); return 0;
    }
}
static simd_float4 fetchAttribute(const uint8_t *source, unsigned type) {
    simd_float4 result = {0, 0, 0, 1};
    if (type == 0x16) { memcpy(&result, source, 4); return result; } // shader unpacks the original bits
    if (type == 0x40) return {source[2] / 255.0f, source[1] / 255.0f, source[0] / 255.0f, source[3] / 255.0f};
    unsigned count = type == 0x72 ? 3 : type >> 4, format = type & 15;
    require(count >= 1 && count <= 4, @"Invalid Xbox vertex component count");
    for (unsigned component = 0; component < count; component++) {
        if (format == 2) { float value; memcpy(&value, source + component * 4, 4); result[component] = value; }
        else if (format == 1 || format == 5) {
            int16_t value; memcpy(&value, source + component * 2, 2);
            result[component] = format == 1 ? std::max(-1.0f, value / 32767.0f) : (float)value;
        } else if (format == 4) result[component] = source[component] / 255.0f;
        else require(false, @"Unsupported Xbox vertex conversion");
        require(std::isfinite(result[component]), @"Non-finite vertex attribute");
    }
    return result;
}
struct Stream { NSData *data; NSUInteger stride, offset, firstVertex; };
struct Element { unsigned reg, stream, type; NSUInteger offset, bytes; };
struct Geometry {
    std::vector<Inputs> vertices;
    std::vector<uint32_t> indices;
    MTLPrimitiveType primitive;
    MTLPrimitiveTopologyClass topology;
    uint32_t packedMask;
    NSUInteger sourceVertexFirst, sourceVertexCount, sourceIndexCount;
};
static Geometry geometry(Resources &resources, NSDictionary *manifest) {
    NSDictionary *declaration = manifest[@"vertex_declaration"], *draw = manifest[@"draw"];
    require([declaration isKindOfClass:NSDictionary.class] && [draw isKindOfClass:NSDictionary.class], @"Missing draw/declaration");
    Geometry result = {};
    result.packedMask = (uint32_t)integer(declaration[@"packed_mask"], 65535, @"Invalid packed attribute mask");
    Stream streams[16] = {};
    require([manifest[@"vertex_streams"] isKindOfClass:NSArray.class], @"Missing captured vertex streams");
    for (NSDictionary *description in manifest[@"vertex_streams"]) {
        unsigned index = (unsigned)integer(description[@"stream"], 15, @"Invalid vertex stream index");
        require(streams[index].data == nil, @"Duplicate vertex stream");
        Stream &stream = streams[index];
        stream.data = resources.load(description);
        stream.stride = integer(description[@"stride"], 65535, @"Invalid Xbox vertex stride");
        stream.offset = description[@"offset"] ? integer(description[@"offset"], stream.data.length, @"Invalid vertex stream offset") : 0;
        stream.firstVertex = description[@"first_vertex"] ? integer(description[@"first_vertex"], UINT32_MAX, @"Invalid vertex stream origin") : 0;
    }
    std::vector<Element> elements;
    bool seen[16] = {}; uint32_t packedMask = 0;
    require([declaration[@"elements"] isKindOfClass:NSArray.class] && [declaration[@"elements"] count] <= 16,
            @"Missing or oversized vertex declaration");
    for (NSDictionary *description in declaration[@"elements"]) {
        Element element = {};
        element.reg = (unsigned)integer(description[@"register"], 15, @"Invalid Xbox vertex register");
        element.stream = (unsigned)integer(description[@"stream"], 15, @"Invalid declaration stream");
        element.offset = integer(description[@"offset"], 65535, @"Invalid attribute byte offset");
        element.type = (unsigned)integer(description[@"type"], 255, @"Invalid Xbox attribute format");
        element.bytes = attributeBytes(element.type);
        require(!seen[element.reg], @"Duplicate declaration vertex register"); seen[element.reg] = true;
        if (element.type == 0x16) packedMask |= 1u << element.reg;
        elements.push_back(element);
    }
    require(packedMask == result.packedMask, @"Declaration and emitted shader packed masks differ");
    Inputs fixed = {};
    id fixedDescription = manifest[@"fixed_attributes"];
    if ([fixedDescription isKindOfClass:NSDictionary.class]) {
        NSData *data = resources.load(fixedDescription);
        require(data.length == sizeof(fixed), @"Fixed vertex register byte count mismatch");
        finiteFloats(data, @"Non-finite fixed vertex register"); memcpy(&fixed, data.bytes, sizeof(fixed));
    } else {
        require([fixedDescription isKindOfClass:NSArray.class] && [fixedDescription count] == 16, @"Missing sixteen fixed vertex registers");
        for (unsigned reg = 0; reg < 16; reg++) fixed.v[reg] = vector4(fixedDescription[reg], @"Invalid fixed vertex register");
    }
    // Missing packed streams use integer zero, matching setup_streams's fixed
    // packed-register binding. Float fixed registers retain their captured values.
    for (unsigned reg = 0; reg < 16; reg++) if (packedMask & (1u << reg)) fixed.v[reg] = {0, 0, 0, 1};
    bool indexed = boolean(draw[@"indexed"], @"Missing indexed draw flag");
    int64_t base = draw[@"base_vertex"] ? (int64_t)number(draw[@"base_vertex"], INT32_MIN, UINT32_MAX, true, @"Invalid base vertex") : 0;
    std::vector<uint32_t> raw;
    if (indexed) {
        NSData *data = resources.load(draw[@"index_buffer"]);
        NSUInteger count = integer(draw[@"index_count"], 4 * 1024 * 1024, @"Invalid captured index count");
        NSUInteger offset = draw[@"index_offset_bytes"] ? integer(draw[@"index_offset_bytes"], data.length, @"Invalid index byte offset") : 0;
        NSString *type = draw[@"index_type"];
        NSUInteger bytes = [type isEqualToString:@"uint16"] ? 2 : [type isEqualToString:@"uint32"] ? 4 : 0;
        require(bytes && offset % bytes == 0 && count && count <= (data.length - offset) / bytes, @"Invalid index buffer range/type");
        for (NSUInteger index = 0; index < count; index++) {
            uint32_t value = 0; memcpy(&value, (const uint8_t *)data.bytes + offset + index * bytes, bytes);
            int64_t vertex = base + value;
            require(vertex >= 0 && vertex <= UINT32_MAX, @"Base vertex produces invalid source index");
            raw.push_back((uint32_t)vertex);
        }
    } else {
        NSUInteger first = integer(draw[@"vertex_start"], UINT32_MAX, @"Invalid source vertex start");
        NSUInteger count = integer(draw[@"vertex_count"], 4 * 1024 * 1024, @"Invalid source vertex count");
        require(count && first <= UINT32_MAX - count, @"Invalid nonindexed source vertex range");
        require(base == 0, @"Nonindexed draw cannot have a base vertex");
        for (NSUInteger vertex = first; vertex < first + count; vertex++) raw.push_back((uint32_t)vertex);
    }
    result.sourceIndexCount = raw.size();
    auto bounds = std::minmax_element(raw.begin(), raw.end());
    result.sourceVertexFirst = *bounds.first;
    result.sourceVertexCount = (NSUInteger)*bounds.second - *bounds.first + 1;
    require(result.sourceVertexCount <= 1024 * 1024, @"Captured source vertex range is too large");
    result.vertices.resize(result.sourceVertexCount, fixed);
    for (const Element &element : elements) {
        const Stream &stream = streams[element.stream];
        if (!element.bytes || !stream.data) continue;
        require(element.offset <= stream.data.length - stream.offset && element.bytes <= stream.data.length - stream.offset - element.offset,
                @"Vertex declaration exceeds captured stream");
        for (NSUInteger index = 0; index < result.sourceVertexCount; index++) {
            NSUInteger vertex = result.sourceVertexFirst + index;
            require(vertex >= stream.firstVertex, @"Captured stream starts after referenced vertex");
            NSUInteger relative = vertex - stream.firstVertex;
            NSUInteger available = stream.data.length - stream.offset - element.offset - element.bytes;
            require(!stream.stride || relative <= available / stream.stride, @"Vertex fetch exceeds captured raw stream");
            NSUInteger offset = stream.offset + element.offset + relative * stream.stride;
            result.vertices[index].v[element.reg] = fetchAttribute((const uint8_t *)stream.data.bytes + offset, element.type);
        }
    }
    for (uint32_t &index : raw) index -= (uint32_t)result.sourceVertexFirst;
    NSString *primitive = draw[@"primitive"];
    result.topology = MTLPrimitiveTopologyClassTriangle;
    result.primitive = MTLPrimitiveTypeTriangle;
    if ([primitive isEqualToString:@"quad"]) {
        require(raw.size() % 4 == 0, @"Incomplete original quad list");
        for (NSUInteger i = 0; i < raw.size(); i += 4)
            for (unsigned j : {0u, 1u, 2u, 0u, 2u, 3u}) result.indices.push_back(raw[i + j]);
    } else if ([primitive isEqualToString:@"triangle_fan"]) {
        require(raw.size() >= 3, @"Incomplete original triangle fan");
        for (NSUInteger i = 1; i + 1 < raw.size(); i++) {
            result.indices.push_back(raw[0]); result.indices.push_back(raw[i]); result.indices.push_back(raw[i + 1]);
        }
    } else if ([primitive isEqualToString:@"triangle"]) {
        require(raw.size() % 3 == 0, @"Incomplete original triangle list"); result.indices = raw;
    } else if ([primitive isEqualToString:@"triangle_strip"]) {
        require(raw.size() >= 3, @"Incomplete original triangle strip"); result.indices = raw; result.primitive = MTLPrimitiveTypeTriangleStrip;
    } else if ([primitive isEqualToString:@"point"]) {
        result.indices = raw; result.primitive = MTLPrimitiveTypePoint; result.topology = MTLPrimitiveTopologyClassPoint;
    } else if ([primitive isEqualToString:@"line"]) {
        require(raw.size() % 2 == 0, @"Incomplete original line list");
        result.indices = raw; result.primitive = MTLPrimitiveTypeLine; result.topology = MTLPrimitiveTopologyClassLine;
    } else if ([primitive isEqualToString:@"line_strip"] || [primitive isEqualToString:@"line_loop"]) {
        require(raw.size() >= 2, @"Incomplete original line strip"); result.indices = raw;
        if ([primitive isEqualToString:@"line_loop"]) result.indices.push_back(raw[0]);
        result.primitive = MTLPrimitiveTypeLineStrip; result.topology = MTLPrimitiveTopologyClassLine;
    } else require(false, @"Unsupported original primitive topology");
    return result;
}

static NSUInteger enumeration(id value, NSDictionary *mapping, NSString *label) {
    require([value isKindOfClass:NSString.class] && mapping[value], label);
    return [mapping[value] unsignedIntegerValue];
}
static MTLCompareFunction compare(id value) {
    return (MTLCompareFunction)enumeration(value, @{@"never": @(MTLCompareFunctionNever), @"less": @(MTLCompareFunctionLess),
        @"equal": @(MTLCompareFunctionEqual), @"less_equal": @(MTLCompareFunctionLessEqual), @"greater": @(MTLCompareFunctionGreater),
        @"not_equal": @(MTLCompareFunctionNotEqual), @"greater_equal": @(MTLCompareFunctionGreaterEqual), @"always": @(MTLCompareFunctionAlways)},
        @"Unsupported depth/stencil comparison");
}
static MTLStencilOperation stencilOperation(id value) {
    return (MTLStencilOperation)enumeration(value, @{@"keep": @(MTLStencilOperationKeep), @"zero": @(MTLStencilOperationZero),
        @"replace": @(MTLStencilOperationReplace), @"increment_clamp": @(MTLStencilOperationIncrementClamp),
        @"decrement_clamp": @(MTLStencilOperationDecrementClamp), @"invert": @(MTLStencilOperationInvert),
        @"increment_wrap": @(MTLStencilOperationIncrementWrap), @"decrement_wrap": @(MTLStencilOperationDecrementWrap)},
        @"Unsupported stencil operation");
}
static MTLBlendFactor blendFactor(id value) {
    return (MTLBlendFactor)enumeration(value, @{@"zero": @(MTLBlendFactorZero), @"one": @(MTLBlendFactorOne),
        @"source_color": @(MTLBlendFactorSourceColor), @"one_minus_source_color": @(MTLBlendFactorOneMinusSourceColor),
        @"source_alpha": @(MTLBlendFactorSourceAlpha), @"one_minus_source_alpha": @(MTLBlendFactorOneMinusSourceAlpha),
        @"destination_color": @(MTLBlendFactorDestinationColor), @"one_minus_destination_color": @(MTLBlendFactorOneMinusDestinationColor),
        @"destination_alpha": @(MTLBlendFactorDestinationAlpha), @"one_minus_destination_alpha": @(MTLBlendFactorOneMinusDestinationAlpha),
        @"source_alpha_saturated": @(MTLBlendFactorSourceAlphaSaturated), @"blend_color": @(MTLBlendFactorBlendColor),
        @"one_minus_blend_color": @(MTLBlendFactorOneMinusBlendColor), @"blend_alpha": @(MTLBlendFactorBlendAlpha),
        @"one_minus_blend_alpha": @(MTLBlendFactorOneMinusBlendAlpha)}, @"Unsupported original blend factor");
}
static MTLBlendOperation blendOperation(id value) {
    return (MTLBlendOperation)enumeration(value, @{@"add": @(MTLBlendOperationAdd), @"subtract": @(MTLBlendOperationSubtract),
        @"reverse_subtract": @(MTLBlendOperationReverseSubtract), @"min": @(MTLBlendOperationMin), @"max": @(MTLBlendOperationMax)},
        @"Unsupported original blend operation");
}
static MTLSamplerAddressMode address(id value) {
    return (MTLSamplerAddressMode)enumeration(value, @{@"repeat": @(MTLSamplerAddressModeRepeat),
        @"mirror_repeat": @(MTLSamplerAddressModeMirrorRepeat), @"clamp_to_edge": @(MTLSamplerAddressModeClampToEdge)},
        @"Unsupported native sampler address; border must be emitted explicitly");
}

static void bindTextures(id<MTLDevice> device, id<MTLRenderCommandEncoder> encoder, Resources &resources, NSArray *descriptions) {
    require([descriptions isKindOfClass:NSArray.class] && descriptions.count == 4, @"Missing four captured texture slots");
    for (NSUInteger slot = 0; slot < 4; slot++) {
        id record = descriptions[slot]; if (record == NSNull.null) continue;
        require([record isKindOfClass:NSDictionary.class], @"Invalid captured texture descriptor");
        bool cube = [record[@"type"] isEqualToString:@"cube"];
        require((cube || [record[@"type"] isEqualToString:@"2d"]) &&
                integer(record[@"slot"], 3, @"Invalid captured texture slot") == slot, @"Unsupported captured texture dimension/slot");
        NSUInteger width = integer(record[@"width"], 4096, @"Invalid texture width"), height = integer(record[@"height"], 4096, @"Invalid texture height");
        require(width && height && (!cube || width == height), @"Zero-size or nonsquare captured cube texture");
        NSString *format = record[@"pixel_format"];
        MTLPixelFormat pixelFormat = (MTLPixelFormat)enumeration(format, @{@"rgba8unorm": @(MTLPixelFormatRGBA8Unorm),
            @"bc1_rgba": @(MTLPixelFormatBC1_RGBA), @"bc2_rgba": @(MTLPixelFormatBC2_RGBA), @"bc3_rgba": @(MTLPixelFormatBC3_RGBA)},
            @"Unsupported captured texture upload format");
        bool compressed = pixelFormat != MTLPixelFormatRGBA8Unorm;
        require(!cube || !compressed || pixelFormat == MTLPixelFormatBC1_RGBA,
                @"BC2/BC3 cube replay has not been validated");
        if (compressed) require(device.supportsBCTextureCompression, @"Device does not support original BC texture blocks");
        NSArray *mips = record[@"mipmaps"];
        NSUInteger maximum = 1; for (NSUInteger size = std::max(width, height); size > 1; size >>= 1) maximum++;
        require([mips isKindOfClass:NSArray.class] && mips.count && mips.count <= maximum, @"Invalid authored mip chain");
        MTLTextureDescriptor *description = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pixelFormat
            width:width height:height mipmapped:mips.count > 1];
        if (cube) description.textureType = MTLTextureTypeCube;
        description.mipmapLevelCount = mips.count; description.storageMode = MTLStorageModeShared;
        description.usage = MTLTextureUsageShaderRead;
        id<MTLTexture> texture = [device newTextureWithDescriptor:description]; require(texture != nil, @"Captured texture allocation failed");
        for (NSUInteger level = 0; level < mips.count; level++) {
            NSDictionary *mip = mips[level];
            require([mip isKindOfClass:NSDictionary.class], @"Invalid authored mip descriptor");
            NSUInteger w = std::max((NSUInteger)1, width >> level), h = std::max((NSUInteger)1, height >> level);
            require(integer(mip[@"width"], 4096, @"Invalid mip width") == w && integer(mip[@"height"], 4096, @"Invalid mip height") == h,
                    @"Authored mip dimensions differ from texture chain");
            NSUInteger block = pixelFormat == MTLPixelFormatBC1_RGBA ? 8 : 16;
            NSUInteger row = compressed ? ((w + 3) / 4) * block : w * 4, rows = compressed ? (h + 3) / 4 : h;
            NSArray *images = cube ? mip[@"faces"] : @[mip];
            require([images isKindOfClass:NSArray.class] && images.count == (cube ? 6 : 1), @"Captured mip requires every original cube face");
            if (cube) require(integer(mip[@"level"], maximum - 1, @"Invalid cube mip level") == level, @"Cube mip levels are out of order");
            unsigned uploadedFaces = 0;
            for (NSDictionary *image in images) {
                require([image isKindOfClass:NSDictionary.class], @"Invalid captured mip face descriptor");
                NSUInteger face = cube ? integer(image[@"face"], 5, @"Invalid captured cube face") : 0;
                require(!(uploadedFaces & (1u << face)), @"Duplicate captured cube face"); uploadedFaces |= 1u << face;
                require(integer(image[@"bytes_per_row"], UINT32_MAX, @"Invalid mip row bytes") == row &&
                        integer(image[@"bytes_per_image"], UINT32_MAX, @"Invalid mip image bytes") == row * rows, @"Captured mip row/image layout mismatch");
                NSData *data = resources.load(image); require(data.length == row * rows, @"Captured authored mip byte count mismatch");
                if (cube) [texture replaceRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:level slice:face
                                       withBytes:data.bytes bytesPerRow:row bytesPerImage:row * rows];
                else [texture replaceRegion:MTLRegionMake2D(0, 0, w, h) mipmapLevel:level withBytes:data.bytes bytesPerRow:row];
            }
        }
        NSDictionary *s = record[@"sampler"]; require([s isKindOfClass:NSDictionary.class], @"Missing captured sampler state");
        MTLSamplerDescriptor *sampler = [MTLSamplerDescriptor new];
        NSDictionary *filters = @{@"nearest": @(MTLSamplerMinMagFilterNearest), @"linear": @(MTLSamplerMinMagFilterLinear)};
        sampler.minFilter = (MTLSamplerMinMagFilter)enumeration(s[@"min_filter"], filters, @"Unsupported minification filter");
        sampler.magFilter = (MTLSamplerMinMagFilter)enumeration(s[@"mag_filter"], filters, @"Unsupported magnification filter");
        sampler.mipFilter = (MTLSamplerMipFilter)enumeration(s[@"mip_filter"], @{@"none": @(MTLSamplerMipFilterNotMipmapped),
            @"nearest": @(MTLSamplerMipFilterNearest), @"linear": @(MTLSamplerMipFilterLinear)}, @"Unsupported mip filter");
        sampler.sAddressMode = address(s[@"address_u"]); sampler.tAddressMode = address(s[@"address_v"]); sampler.rAddressMode = address(s[@"address_w"]);
        sampler.lodMinClamp = (float)number(s[@"lod_min"], 0, mips.count - 1, false, @"Invalid original minimum mip");
        sampler.lodMaxClamp = (float)number(s[@"lod_max"], sampler.lodMinClamp, mips.count - 1, false, @"Invalid original maximum mip");
        sampler.maxAnisotropy = integer(s[@"max_anisotropy"], 16, @"Invalid original anisotropy"); require(sampler.maxAnisotropy >= 1, @"Zero anisotropy");
        id<MTLSamplerState> state = [device newSamplerStateWithDescriptor:sampler]; require(state != nil, @"Native sampler creation failed");
        [encoder setFragmentTexture:texture atIndex:slot]; [encoder setFragmentSamplerState:state atIndex:slot];
    }
}

static void validateShaderTextureTypes(MTLRenderPipelineReflection *reflection, NSArray *descriptions) {
    require(reflection != nil && [descriptions isKindOfClass:NSArray.class] && descriptions.count == 4,
            @"Missing native shader texture reflection");
    for (id<MTLBinding> argument in reflection.fragmentBindings) {
        if (argument.type != MTLBindingTypeTexture || !argument.used) continue;
        require(argument.index < descriptions.count, @"Generated fragment shader uses an unsupported texture slot");
        id record = descriptions[argument.index];
        require([record isKindOfClass:NSDictionary.class], @"Generated fragment shader requires an absent captured texture");
        MTLTextureType expected = [record[@"type"] isEqualToString:@"cube"] ? MTLTextureTypeCube : MTLTextureType2D;
        require(((id<MTLTextureBinding>)argument).textureType == expected,
                @"Generated fragment shader and captured texture dimensions differ");
    }
}

static void complete(id<MTLCommandBuffer> command) {
    [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted, command.error.localizedDescription ?: @"Native replay command failed");
}
static NSData *tightRows(id<MTLBuffer> buffer, NSUInteger rowBytes, NSUInteger tightBytes, NSUInteger height) {
    NSMutableData *result = [NSMutableData dataWithLength:tightBytes * height];
    for (NSUInteger row = 0; row < height; row++)
        memcpy((uint8_t *)result.mutableBytes + row * tightBytes, (const uint8_t *)buffer.contents + row * rowBytes, tightBytes);
    return result;
}
static id<MTLBuffer> paddedRows(id<MTLDevice> device, NSData *data, NSUInteger tight, NSUInteger padded, NSUInteger height) {
    require(data.length == tight * height, @"Initial attachment byte count mismatch");
    id<MTLBuffer> buffer = [device newBufferWithLength:padded * height options:MTLResourceStorageModeShared];
    require(buffer != nil, @"Attachment transfer allocation failed"); memset(buffer.contents, 0, buffer.length);
    for (NSUInteger row = 0; row < height; row++) memcpy((uint8_t *)buffer.contents + row * padded, (const uint8_t *)data.bytes + row * tight, tight);
    return buffer;
}
static NSDictionary *writeOutput(NSString *directory, NSString *name, NSData *data, NSString *format, NSUInteger width, NSUInteger height) {
    require([data writeToFile:[directory stringByAppendingPathComponent:name] atomically:YES], @"Could not save replay output");
    return @{@"file": name, @"sha256": sha256(data), @"size": @(data.length), @"format": format,
             @"width": @(width), @"height": @(height), @"orientation": @"top_left"};
}

int main(int argc, const char **argv) { @autoreleasepool {
    require(argc == 3, @"Usage: draw_replay replay.json output_directory");
    NSString *path = [@(argv[1]).stringByStandardizingPath stringByResolvingSymlinksInPath];
    if (!path.isAbsolutePath) path = [NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:path];
    NSString *output = [@(argv[2]).stringByStandardizingPath stringByResolvingSymlinksInPath];
    if (!output.isAbsolutePath) output = [NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:output];
    NSData *manifestData = readFile(path); NSString *manifestHash = sha256(manifestData);
    NSError *error = nil; NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:manifestData options:0 error:&error];
    require([manifest isKindOfClass:NSDictionary.class] && [manifest[@"kind"] isEqualToString:@"nv2a_draw_replay"] &&
            integer(manifest[@"schema_version"], 1, @"Invalid replay schema") == 1, @"Unsupported actual-draw replay manifest");
    NSString *runnerPath = [[NSProcessInfo.processInfo.arguments firstObject] stringByResolvingSymlinksInPath];
    if (!runnerPath.isAbsolutePath) runnerPath = [NSFileManager.defaultManager.currentDirectoryPath stringByAppendingPathComponent:runnerPath];
    NSString *runnerHash = sha256(readFile(runnerPath));
    Resources resources = {path.stringByDeletingLastPathComponent, [NSMutableDictionary new]};
    NSDictionary *preparedSources = manifest[@"source_sha256"];
    require([preparedSources isKindOfClass:NSDictionary.class] && preparedSources.count,
            @"Missing prepared emitter/importer/runner source provenance");
    for (NSString *source in preparedSources) {
        require(source.isAbsolutePath && [preparedSources[source] isKindOfClass:NSString.class] &&
                [sha256(readFile(source)) isEqualToString:preparedSources[source]], @"Replay source differs from prepared package");
        resources.hashes[source] = preparedSources[source];
    }
    Geometry inputs = geometry(resources, manifest);
    NSData *vertexData = resources.load(manifest[@"uniforms"][@"vertex"]), *pixelData = resources.load(manifest[@"uniforms"][@"pixel"]);
    require(vertexData.length == sizeof(VertexUniforms) && pixelData.length == sizeof(PixelUniforms), @"Generated shader uniform byte count mismatch");
    finiteFloats(vertexData, @"Non-finite captured vertex constants"); finiteFloats(pixelData, @"Non-finite captured pixel uniforms");
    const VertexUniforms *vu = (const VertexUniforms *)vertexData.bytes;
    require(vu->viewportScale.x != 0 && vu->viewportScale.y != 0 && vu->viewportScale.z != 0 && vu->pointSize > 0,
            @"Invalid captured viewport undo/point size state");
    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No Metal device");
    id<MTLCommandQueue> queue = [device newCommandQueue]; require(queue != nil, @"No Metal queue");
    NSDictionary *target = manifest[@"target"], *state = manifest[@"render_state"];
    bool bgraTarget = [target[@"color_format"] isEqualToString:@"bgra8unorm"];
    require([target isKindOfClass:NSDictionary.class] && [state isKindOfClass:NSDictionary.class] &&
            (bgraTarget || [target[@"color_format"] isEqualToString:@"rgba8unorm"]) && [target[@"orientation"] isEqualToString:@"top_left"] &&
            [target[@"depth_format"] isEqualToString:@"depth32float_stencil8"], @"Unsupported native replay attachment/orientation");
    if (target[@"sample_count"]) require(integer(target[@"sample_count"], 1, @"Unsupported MSAA target") == 1, @"Unsupported MSAA target");
    NSUInteger width = integer(target[@"width"], 4096, @"Invalid target width"), height = integer(target[@"height"], 4096, @"Invalid target height");
    require(width && height, @"Zero-size replay target");
    simd_float4 clear = vector4(target[@"clear_color"], @"Missing original clear color");
    for (unsigned i = 0; i < 4; i++) require(clear[i] >= 0 && clear[i] <= 1, @"Invalid clear color range");
    double clearDepth = number(target[@"clear_depth"], 0, 1, false, @"Invalid original clear depth");
    unsigned clearStencil = (unsigned)integer(target[@"clear_stencil"], 255, @"Invalid original clear stencil");
    id<MTLLibrary> vl = library(device, resources, manifest[@"shaders"][@"vertex"]), fl = library(device, resources, manifest[@"shaders"][@"fragment"]);
    require([manifest[@"shaders"][@"vertex"][@"entry"] isEqualToString:@"xgpu_vertex"] &&
            [manifest[@"shaders"][@"fragment"][@"entry"] isEqualToString:@"xgpu_fragment"], @"Replay requires original generated shader entries");
    MTLRenderPipelineDescriptor *pipelineDescription = [MTLRenderPipelineDescriptor new];
    pipelineDescription.vertexFunction = [vl newFunctionWithName:@"xgpu_vertex"];
    pipelineDescription.fragmentFunction = [fl newFunctionWithName:@"xgpu_fragment"];
    require(pipelineDescription.vertexFunction && pipelineDescription.fragmentFunction, @"Generated shader entry missing");
    pipelineDescription.depthAttachmentPixelFormat = pipelineDescription.stencilAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
    // NV2A exports point size for every program, including triangle draws.
    // Metal rejects that output when a triangle topology is declared here;
    // actual primitive topology remains specified by the draw call below.
    pipelineDescription.inputPrimitiveTopology = MTLPrimitiveTopologyClassUnspecified;
    MTLVertexDescriptor *layout = [MTLVertexDescriptor vertexDescriptor];
    for (unsigned reg = 0; reg < 16; reg++) {
        layout.attributes[reg].format = (inputs.packedMask & (1u << reg)) ? MTLVertexFormatUInt : MTLVertexFormatFloat4;
        layout.attributes[reg].offset = reg * sizeof(simd_float4); layout.attributes[reg].bufferIndex = 1;
    }
    layout.layouts[1].stride = sizeof(Inputs); pipelineDescription.vertexDescriptor = layout;
    NSDictionary *blend = state[@"blend"], *depth = state[@"depth"], *stencil = state[@"stencil"], *raster = state[@"raster"];
    require([blend isKindOfClass:NSDictionary.class] && [depth isKindOfClass:NSDictionary.class] &&
            [stencil isKindOfClass:NSDictionary.class] && [raster isKindOfClass:NSDictionary.class], @"Missing original raster state");
    MTLRenderPipelineColorAttachmentDescriptor *attachment = pipelineDescription.colorAttachments[0];
    attachment.pixelFormat = bgraTarget ? MTLPixelFormatBGRA8Unorm : MTLPixelFormatRGBA8Unorm;
    attachment.blendingEnabled = boolean(blend[@"enabled"], @"Missing original blend enable");
    attachment.sourceRGBBlendFactor = attachment.sourceAlphaBlendFactor = blendFactor(blend[@"source"]);
    attachment.destinationRGBBlendFactor = attachment.destinationAlphaBlendFactor = blendFactor(blend[@"destination"]);
    attachment.rgbBlendOperation = attachment.alphaBlendOperation = blendOperation(blend[@"operation"]);
    unsigned mask = (unsigned)integer(blend[@"write_mask"], 15, @"Invalid original color write mask");
    attachment.writeMask = (MTLColorWriteMask)(((mask & 1) ? MTLColorWriteMaskRed : 0) | ((mask & 2) ? MTLColorWriteMaskGreen : 0) |
        ((mask & 4) ? MTLColorWriteMaskBlue : 0) | ((mask & 8) ? MTLColorWriteMaskAlpha : 0));
    MTLRenderPipelineReflection *reflection = nil;
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:pipelineDescription
        options:MTLPipelineOptionBindingInfo reflection:&reflection error:&error];
    require(pipeline != nil, error.localizedDescription ?: @"Native original-shader pipeline failed");
    validateShaderTextureTypes(reflection, manifest[@"textures"]);
    MTLDepthStencilDescriptor *depthDescription = [MTLDepthStencilDescriptor new];
    bool depthEnabled = boolean(depth[@"enabled"], @"Missing depth enable");
    MTLCompareFunction originalDepthCompare = compare(depth[@"compare"]);
    bool originalDepthWrite = boolean(depth[@"write"], @"Missing depth write state");
    depthDescription.depthCompareFunction = depthEnabled ? originalDepthCompare : MTLCompareFunctionAlways;
    depthDescription.depthWriteEnabled = depthEnabled && originalDepthWrite;
    if (boolean(stencil[@"enabled"], @"Missing stencil enable")) {
        MTLStencilDescriptor *description = [MTLStencilDescriptor new];
        description.stencilCompareFunction = compare(stencil[@"compare"]);
        description.readMask = (uint32_t)integer(stencil[@"read_mask"], UINT32_MAX, @"Invalid stencil read mask");
        description.writeMask = (uint32_t)integer(stencil[@"write_mask"], UINT32_MAX, @"Invalid stencil write mask");
        description.stencilFailureOperation = stencilOperation(stencil[@"fail"]);
        description.depthFailureOperation = stencilOperation(stencil[@"depth_fail"]);
        description.depthStencilPassOperation = stencilOperation(stencil[@"pass"]);
        depthDescription.frontFaceStencil = description; depthDescription.backFaceStencil = description;
    }
    id<MTLDepthStencilState> depthState = [device newDepthStencilStateWithDescriptor:depthDescription]; require(depthState != nil, @"Native depth/stencil state failed");
    MTLTextureDescriptor *textureDescription = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:attachment.pixelFormat width:width height:height mipmapped:NO];
    textureDescription.usage = MTLTextureUsageRenderTarget; textureDescription.storageMode = MTLStorageModeShared;
    id<MTLTexture> color = [device newTextureWithDescriptor:textureDescription];
    textureDescription.pixelFormat = MTLPixelFormatDepth32Float_Stencil8; textureDescription.storageMode = MTLStorageModePrivate;
    id<MTLTexture> depthTarget = [device newTextureWithDescriptor:textureDescription]; require(color && depthTarget, @"Replay target allocation failed");
    if (target[@"initial_color"]) {
        NSData *data = resources.load(target[@"initial_color"]); require(data.length == width * height * 4, @"Initial RGBA8 byte count mismatch");
        NSMutableData *bgra = [data mutableCopy]; uint8_t *bytes = (uint8_t *)bgra.mutableBytes;
        if (bgraTarget) for (NSUInteger i = 0; i < width * height; i++) std::swap(bytes[i * 4], bytes[i * 4 + 2]);
        [color replaceRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0 withBytes:bgra.bytes bytesPerRow:width * 4];
    }
    NSUInteger depthRow = (width * 4 + 255) & ~(NSUInteger)255, stencilRow = (width + 255) & ~(NSUInteger)255;
    if (target[@"initial_depth"] || target[@"initial_stencil"]) {
        id<MTLCommandBuffer> command = [queue commandBuffer]; id<MTLBlitCommandEncoder> encoder = [command blitCommandEncoder];
        for (NSString *field in @[@"initial_depth", @"initial_stencil"]) if (target[field]) {
            NSData *data = resources.load(target[field]); bool isDepth = [field isEqualToString:@"initial_depth"];
            if (isDepth) { finiteFloats(data, @"Invalid initial depth samples"); const float *values = (const float *)data.bytes;
                for (NSUInteger i = 0; i < data.length / 4; i++) require(values[i] >= 0 && values[i] <= 1, @"Initial depth sample outside0..1"); }
            NSUInteger row = isDepth ? depthRow : stencilRow;
            id<MTLBuffer> buffer = paddedRows(device, data, width * (isDepth ? 4 : 1), row, height);
            [encoder copyFromBuffer:buffer sourceOffset:0 sourceBytesPerRow:row sourceBytesPerImage:row * height sourceSize:MTLSizeMake(width, height, 1)
                          toTexture:depthTarget destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0, 0, 0)
                            options:isDepth ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionStencilFromDepthStencil];
        }
        [encoder endEncoding]; complete(command);
    }
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = color; pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].loadAction = target[@"initial_color"] ? MTLLoadActionLoad : MTLLoadActionClear;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(clear.x, clear.y, clear.z, clear.w);
    pass.depthAttachment.texture = depthTarget; pass.depthAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.loadAction = target[@"initial_depth"] ? MTLLoadActionLoad : MTLLoadActionClear; pass.depthAttachment.clearDepth = clearDepth;
    pass.stencilAttachment.texture = depthTarget; pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.stencilAttachment.loadAction = target[@"initial_stencil"] ? MTLLoadActionLoad : MTLLoadActionClear; pass.stencilAttachment.clearStencil = clearStencil;
    id<MTLBuffer> vertexBuffer = [device newBufferWithBytes:inputs.vertices.data() length:inputs.vertices.size() * sizeof(Inputs) options:MTLResourceStorageModeShared];
    id<MTLBuffer> indexBuffer = [device newBufferWithBytes:inputs.indices.data() length:inputs.indices.size() * 4 options:MTLResourceStorageModeShared];
    require(vertexBuffer && indexBuffer, @"Original vertex/index transfer allocation failed");
    id<MTLCommandBuffer> command = [queue commandBuffer]; id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    require(encoder != nil, @"Replay render encoder failed"); [encoder setRenderPipelineState:pipeline]; [encoder setDepthStencilState:depthState];
    NSDictionary *vp = state[@"viewport"], *scissor = state[@"scissor"];
    MTLViewport viewport = {number(vp[@"x"], -65535, 65535, false, @"Invalid viewport X"), number(vp[@"y"], -65535, 65535, false, @"Invalid viewport Y"),
        number(vp[@"width"], 1, 16384, false, @"Invalid viewport width"), number(vp[@"height"], 1, 16384, false, @"Invalid viewport height"),
        number(vp[@"znear"], 0, 1, false, @"Invalid viewport minimum depth"), number(vp[@"zfar"], 0, 1, false, @"Invalid viewport maximum depth")};
    require(viewport.znear <= viewport.zfar, @"Reversed viewport depth requires explicit support"); [encoder setViewport:viewport];
    MTLScissorRect rectangle = {integer(scissor[@"x"], width, @"Invalid scissor X"), integer(scissor[@"y"], height, @"Invalid scissor Y"),
        integer(scissor[@"width"], width, @"Invalid scissor width"), integer(scissor[@"height"], height, @"Invalid scissor height")};
    require(rectangle.width && rectangle.height && rectangle.width <= width - rectangle.x && rectangle.height <= height - rectangle.y,
            @"Scissor exceeds native target"); [encoder setScissorRect:rectangle];
    [encoder setFrontFacingWinding:(MTLWinding)enumeration(raster[@"front_face"], @{@"cw": @(MTLWindingClockwise), @"ccw": @(MTLWindingCounterClockwise)}, @"Invalid original front winding")];
    [encoder setCullMode:(MTLCullMode)enumeration(raster[@"cull"], @{@"none": @(MTLCullModeNone), @"front": @(MTLCullModeFront), @"back": @(MTLCullModeBack)}, @"Invalid original face culling")];
    [encoder setTriangleFillMode:(MTLTriangleFillMode)enumeration(raster[@"fill"], @{@"solid": @(MTLTriangleFillModeFill), @"wireframe": @(MTLTriangleFillModeLines)}, @"Unsupported original fill mode")];
    [encoder setDepthBias:(float)number(raster[@"depth_bias"], -FLT_MAX, FLT_MAX, false, @"Invalid original depth offset")
              slopeScale:(float)number(raster[@"slope_scale"], -FLT_MAX, FLT_MAX, false, @"Invalid original slope offset")
                   clamp:(float)number(raster[@"depth_bias_clamp"], -FLT_MAX, FLT_MAX, false, @"Invalid original depth offset clamp")];
    [encoder setStencilReferenceValue:(uint32_t)integer(stencil[@"reference"], UINT32_MAX, @"Invalid original stencil reference")];
    simd_float4 blendColor = blend[@"color"] ? vector4(blend[@"color"], @"Invalid original blend color") : (simd_float4){0, 0, 0, 0};
    [encoder setBlendColorRed:blendColor.x green:blendColor.y blue:blendColor.z alpha:blendColor.w];
    [encoder setVertexBuffer:vertexBuffer offset:0 atIndex:1]; [encoder setVertexBytes:vertexData.bytes length:vertexData.length atIndex:0];
    [encoder setFragmentBytes:pixelData.bytes length:pixelData.length atIndex:0]; bindTextures(device, encoder, resources, manifest[@"textures"]);
    [encoder drawIndexedPrimitives:inputs.primitive indexCount:inputs.indices.size() indexType:MTLIndexTypeUInt32 indexBuffer:indexBuffer indexBufferOffset:0];
    [encoder endEncoding]; complete(command);
    id<MTLBuffer> depthBuffer = [device newBufferWithLength:depthRow * height options:MTLResourceStorageModeShared];
    id<MTLBuffer> stencilBuffer = [device newBufferWithLength:stencilRow * height options:MTLResourceStorageModeShared]; require(depthBuffer && stencilBuffer, @"Readback allocation failed");
    id<MTLCommandBuffer> readback = [queue commandBuffer]; id<MTLBlitCommandEncoder> blit = [readback blitCommandEncoder];
    for (unsigned i = 0; i < 2; i++) {
        id<MTLBuffer> buffer = i == 0 ? depthBuffer : stencilBuffer; NSUInteger row = i == 0 ? depthRow : stencilRow;
        [blit copyFromTexture:depthTarget sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(width, height, 1)
                    toBuffer:buffer destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row * height
                      options:i == 0 ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionStencilFromDepthStencil];
    }
    [blit endEncoding]; complete(readback);
    NSMutableData *rgba = [NSMutableData dataWithLength:width * height * 4];
    [color getBytes:rgba.mutableBytes bytesPerRow:width * 4 fromRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0];
    uint8_t *bytes = (uint8_t *)rgba.mutableBytes;
    if (bgraTarget) for (NSUInteger i = 0; i < width * height; i++) std::swap(bytes[i * 4], bytes[i * 4 + 2]);
    NSMutableData *floatingColor = [NSMutableData dataWithLength:width * height * 16];
    float *floats = (float *)floatingColor.mutableBytes;
    for (NSUInteger i = 0; i < width * height * 4; i++) floats[i] = bytes[i] / 255.0f;
    NSData *depthOutput = tightRows(depthBuffer, depthRow, width * 4, height), *stencilOutput = tightRows(stencilBuffer, stencilRow, width, height);
    finiteFloats(depthOutput, @"Non-finite native depth readback"); resources.unchanged();
    require([sha256(readFile(path)) isEqualToString:manifestHash] && [sha256(readFile(runnerPath)) isEqualToString:runnerHash], @"Manifest/runner changed during replay");
    require(![output isEqualToString:resources.root], @"Output directory must not replace replay package resources");
    require([NSFileManager.defaultManager createDirectoryAtPath:output withIntermediateDirectories:YES attributes:nil error:&error], error.localizedDescription ?: @"Could not create output directory");
    NSMutableArray *limits = [NSMutableArray arrayWithArray:manifest[@"limitations"] ?: @[]];
    [limits addObject:@"Native Depth32FloatStencil8; original 24-bit depth storage quantization and its bias precision are not emulated"];
    NSDictionary *result = @{@"schema_version": @1, @"kind": @"nv2a_draw_result", @"complete": @YES, @"backend": @"native_metal",
        @"device": device.name, @"manifest_sha256": manifestHash, @"manifest": @{@"file": path, @"sha256": manifestHash},
        @"runner": @{@"file": runnerPath, @"sha256": runnerHash}, @"source_capture": manifest[@"source_capture"] ?: @{},
        @"shader_sha256": @{@"vertex": manifest[@"shaders"][@"vertex"][@"sha256"], @"fragment": manifest[@"shaders"][@"fragment"][@"sha256"]},
        @"uniform_sha256": @{@"vertex": manifest[@"uniforms"][@"vertex"][@"sha256"], @"pixel": manifest[@"uniforms"][@"pixel"][@"sha256"]},
        @"resource_sha256": resources.hashes, @"source_sha256": preparedSources, @"render_state": state,
        @"depth_format": @"depth32float_stencil8", @"actual_depth_format": @"depth32float_stencil8", @"color_format": target[@"color_format"],
        @"color": writeOutput(output, @"color.rgba", rgba, @"rgba8unorm", width, height),
        @"color_float": writeOutput(output, @"color.f32", floatingColor, @"rgba32float_unorm_readback", width, height),
        @"depth": writeOutput(output, @"depth.f32", depthOutput, @"float32", width, height),
        @"stencil": writeOutput(output, @"stencil.u8", stencilOutput, @"uint8", width, height),
        @"source_vertex_first": @(inputs.sourceVertexFirst), @"source_vertex_count": @(inputs.sourceVertexCount),
        @"source_index_count": @(inputs.sourceIndexCount), @"native_index_count": @(inputs.indices.size()), @"packed_mask": @(inputs.packedMask),
        @"fast_math": @(manifest[@"shaders"][@"vertex"][@"compile_options"] != nil),
        @"shader_compile_options": @{
            @"vertex": manifest[@"shaders"][@"vertex"][@"compile_options"] ?: @{@"fast_math": @NO, @"preserve_invariance": @YES, @"math_mode": @"safe", @"floating_point_functions": @"precise"},
            @"fragment": @{@"fast_math": @NO, @"preserve_invariance": @YES, @"math_mode": @"safe", @"floating_point_functions": @"precise"}},
        @"position_invariance": @YES, @"gpu_ms": @((command.GPUEndTime - command.GPUStartTime) * 1000), @"limits": limits};
    NSData *resultData = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
    require(resultData != nil && [resultData writeToFile:[output stringByAppendingPathComponent:@"result.json"] atomically:YES], @"Could not save replay result");
    fwrite(resultData.bytes, 1, resultData.length, stdout); printf("\n"); return 0;
} }
