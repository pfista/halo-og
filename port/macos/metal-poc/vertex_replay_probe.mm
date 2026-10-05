// Test-only original vertex-stage output capture. It preserves emitted arithmetic
// and invariant raster position, adding an output buffer to inspect clip values.
#define main originalDrawReplayMain
#include "draw_replay.mm"
#undef main

static void verifySources(Resources &resources, NSDictionary *manifest) {
    NSDictionary *sources = manifest[@"source_sha256"];
    require([sources isKindOfClass:NSDictionary.class] && sources.count, @"Missing probe source provenance");
    for (NSString *file in sources) {
        require(file.isAbsolutePath && [sha256(readFile(file)) isEqualToString:sources[file]], @"Prepared probe source has changed");
        resources.hashes[file] = sources[file];
    }
    resources.unchanged();
}

int main(int argc, const char **argv) { @autoreleasepool {
    require(argc == 3 || argc == 4, @"Usage: vertex_replay_probe replay.json output-directory [--fast-math]");
    bool fastMath = argc == 4;
    require(!fastMath || strcmp(argv[3], "--fast-math") == 0, @"Unknown vertex probe option");
    NSString *path = [[@(argv[1]) stringByStandardizingPath] stringByResolvingSymlinksInPath];
    NSData *manifestData = readFile(path);
    NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:manifestData options:0 error:nil];
    require([manifest isKindOfClass:NSDictionary.class], @"Invalid replay manifest");
    Resources resources = {path.stringByDeletingLastPathComponent, [NSMutableDictionary new]};
    verifySources(resources, manifest);
    Geometry inputs = geometry(resources, manifest);
    NSData *vertexUniforms = resources.load(manifest[@"uniforms"][@"vertex"]);
    require(vertexUniforms.length == sizeof(VertexUniforms), @"Captured vertex uniform ABI mismatch");
    NSString *source = [[NSString alloc] initWithData:resources.load(manifest[@"shaders"][@"vertex"])
                                          encoding:NSUTF8StringEncoding];
    NSString *parameter = @"constant XgpuVertexUniforms &uniforms [[buffer(0)]])";
    require([source componentsSeparatedByString:parameter].count == 2 &&
            [source componentsSeparatedByString:@"\treturn output;"].count == 2,
            @"Generated vertex entry does not match the supported probe ABI");
    source = [source stringByReplacingOccurrencesOfString:parameter withString:
        @"constant XgpuVertexUniforms &uniforms [[buffer(0)]], device float4 *captured [[buffer(2)]], uint vertexIndex [[vertex_id]])"];
    source = [source stringByReplacingOccurrencesOfString:@"\treturn output;" withString:
        @"\tcaptured[vertexIndex*10+0] = output.position;\n"
         "\tcaptured[vertexIndex*10+1] = float4(output.point_size, output.xFog, 0.0, 0.0);\n"
         "\tcaptured[vertexIndex*10+2] = output.xD0; captured[vertexIndex*10+3] = output.xD1;\n"
         "\tcaptured[vertexIndex*10+4] = output.xB0; captured[vertexIndex*10+5] = output.xB1;\n"
         "\tcaptured[vertexIndex*10+6] = output.xT0; captured[vertexIndex*10+7] = output.xT1;\n"
         "\tcaptured[vertexIndex*10+8] = output.xT2; captured[vertexIndex*10+9] = output.xT3;\n"
         "\treturn output;"];
    source = [source stringByAppendingString:
        @"\nfragment float4 vertex_probe_fragment() { return float4(0.0); }\n"];
    id<MTLDevice> device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No native Metal device");
    MTLCompileOptions *options = [MTLCompileOptions new];
    options.fastMathEnabled = fastMath; options.preserveInvariance = YES;
    if (@available(macOS 15.0, *)) {
        options.mathMode = fastMath ? MTLMathModeFast : MTLMathModeSafe;
        options.mathFloatingPointFunctions = fastMath ? MTLMathFloatingPointFunctionsFast : MTLMathFloatingPointFunctionsPrecise;
    }
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    require(library != nil, error.localizedDescription ?: @"Vertex output probe compilation failed");
    MTLRenderPipelineDescriptor *description = [MTLRenderPipelineDescriptor new];
    description.vertexFunction = [library newFunctionWithName:@"xgpu_vertex"];
    description.fragmentFunction = [library newFunctionWithName:@"vertex_probe_fragment"];
    description.inputPrimitiveTopology = MTLPrimitiveTopologyClassPoint;
    description.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    MTLVertexDescriptor *layout = [MTLVertexDescriptor new];
    for (unsigned reg = 0; reg < 16; reg++) {
        layout.attributes[reg].format = inputs.packedMask & (1u << reg) ? MTLVertexFormatUInt : MTLVertexFormatFloat4;
        layout.attributes[reg].offset = reg * sizeof(simd_float4); layout.attributes[reg].bufferIndex = 1;
    }
    layout.layouts[1].stride = sizeof(Inputs); description.vertexDescriptor = layout;
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:description error:&error];
    require(pipeline != nil, error.localizedDescription ?: @"Vertex output probe pipeline failed");
    id<MTLBuffer> attributes = [device newBufferWithBytes:inputs.vertices.data()
        length:inputs.vertices.size() * sizeof(Inputs) options:MTLResourceStorageModeShared];
    id<MTLBuffer> captured = [device newBufferWithLength:inputs.vertices.size() * sizeof(simd_float4) * 10
                                              options:MTLResourceStorageModeShared];
    require(attributes != nil && captured != nil, @"Vertex output buffers failed");
    memset(captured.contents, 0xff, captured.length);
    MTLTextureDescriptor *targetDescription = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
        width:1 height:1 mipmapped:NO];
    targetDescription.usage = MTLTextureUsageRenderTarget; targetDescription.storageMode = MTLStorageModeShared;
    id<MTLTexture> target = [device newTextureWithDescriptor:targetDescription]; require(target != nil, @"Vertex probe target failed");
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor new];
    pass.colorAttachments[0].texture = target; pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionDontCare;
    id<MTLCommandQueue> queue = [device newCommandQueue]; id<MTLCommandBuffer> command = [queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:pipeline];
    [encoder setVertexBytes:vertexUniforms.bytes length:vertexUniforms.length atIndex:0];
    [encoder setVertexBuffer:attributes offset:0 atIndex:1]; [encoder setVertexBuffer:captured offset:0 atIndex:2];
    // One original vertex invocation per source vertex avoids write races from
    // repeated indices. Outputs are captured before clipping/rasterization.
    [encoder drawPrimitives:MTLPrimitiveTypePoint vertexStart:0 vertexCount:inputs.vertices.size()];
    [encoder endEncoding]; complete(command);
    NSData *data = [NSData dataWithBytes:captured.contents length:captured.length];
    finiteFloats(data, @"Nonfinite original vertex output in diagnostic capture");
    verifySources(resources, manifest);
    NSString *folder = [[@(argv[2]) stringByStandardizingPath] stringByResolvingSymlinksInPath];
    require(![NSFileManager.defaultManager fileExistsAtPath:folder], @"Preserve existing vertex probe results");
    require([NSFileManager.defaultManager createDirectoryAtPath:folder withIntermediateDirectories:YES attributes:nil error:&error], error.localizedDescription);
    require([data writeToFile:[folder stringByAppendingPathComponent:@"vertices.float32"] atomically:YES], @"Vertex probe output write failed");
    require([[source dataUsingEncoding:NSUTF8StringEncoding] writeToFile:[folder stringByAppendingPathComponent:@"probe.metal"] atomically:YES], @"Vertex probe source write failed");
    NSDictionary *result = @{@"kind": @"nv2a_vertex_output_diagnostic", @"schema_version": @1, @"complete": @YES,
        @"device": device.name, @"manifest_sha256": sha256(manifestData), @"vertex_first": @(inputs.sourceVertexFirst),
        @"vertex_count": @(inputs.vertices.size()), @"stride_bytes": @160,
        @"vectors": @[@"position", @"point_size_fog", @"D0", @"D1", @"B0", @"B1", @"T0", @"T1", @"T2", @"T3"],
        @"clip_depth_range": @"zero_one", @"fast_math": @(fastMath), @"position_invariance": @YES,
        @"data_sha256": sha256(data), @"source_sha256": sha256([source dataUsingEncoding:NSUTF8StringEncoding]),
        @"limits": @[@"Test-only output-buffer wrapper preserves generated arithmetic; no complete draw parity proof.",
                       @"Original vertex stage runs as points to avoid output write races; no triangle interpolation is captured."]};
    NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
    require([json writeToFile:[folder stringByAppendingPathComponent:@"result.json"] atomically:YES], @"Vertex probe result write failed");
    fwrite(json.bytes, 1, json.length, stdout); printf("\n"); return 0;
} }
