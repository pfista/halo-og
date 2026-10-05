#!/usr/bin/env python3
"""Validate Metal visibility API semantics independently of original draw36.

This isolated synthetic fixture does not run Halo or use its shaders/geometry.
Original query records are retained only as source/timing context. Preparation
compiles a standalone executable; --verify checks an already completed GPU run.
No host bridge, shared encoder, capture or prepared frame is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <cstdio>
#include <cstring>
#include <vector>

static void require(bool value, NSString *message) {
    if (!value) { fprintf(stderr, "%s\n", message.UTF8String); exit(1); }
}
static void complete(id<MTLCommandBuffer> command) {
    [command commit]; [command waitUntilCompleted];
    require(command.status == MTLCommandBufferStatusCompleted,
            command.error.localizedDescription ?: @"Visibility GPU command failed");
}
static bool validRegion(NSUInteger size, NSUInteger offset) {
    return offset % 8 == 0 && offset <= size && size - offset >= sizeof(uint64_t);
}
struct Probe { float depth = .25f; uint32_t stencil = 7, discard = 0;
               MTLScissorRect scissor = {0, 0, 32, 24}; };
struct Group { NSUInteger slot; std::vector<Probe> probes; };
struct Constants { float depth; uint32_t discard; };
static id<MTLTexture> color, depth;
static id<MTLDevice> device;
static id<MTLCommandQueue> queue;
static id<MTLRenderPipelineState> pipeline;
static id<MTLDepthStencilState> state;
constexpr uint64_t canary = UINT64_C(0x1122334455667788);

static NSDictionary *run(NSString *name, MTLVisibilityResultMode mode,
                         bool accumulate, const std::vector<Group> &groups,
                         bool separateCommands = false, NSUInteger disabledSlot = NSNotFound) {
    id<MTLBuffer> results = [device newBufferWithLength:64 options:MTLResourceStorageModeShared];
    require(results != nil, @"Visibility result buffer allocation failed");
    uint64_t initial[8]; for (auto &value : initial) value = canary;
    for (const auto &group : groups) {
        require(group.slot < 8 && validRegion(results.length, group.slot * 8), @"Invalid visibility result offset");
        initial[group.slot] = 0;
    }
    memcpy(results.contents, initial, sizeof(initial));
    id<MTLCommandBuffer> command = [queue commandBuffer];
    for (const auto &group : groups) {
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = color;
        pass.colorAttachments[0].loadAction = MTLLoadActionLoad;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.depthAttachment.texture = pass.stencilAttachment.texture = depth;
        pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionLoad;
        pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
        pass.visibilityResultBuffer = results;
        if (@available(macOS 26.0, *)) {
            pass.visibilityResultType = accumulate ? MTLVisibilityResultTypeAccumulate : MTLVisibilityResultTypeReset;
        } else require(!accumulate, @"Cross-encoder accumulation API unavailable");
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        require(encoder != nil, @"Visibility encoder allocation failed");
        [encoder setRenderPipelineState:pipeline]; [encoder setDepthStencilState:state];
        [encoder setCullMode:MTLCullModeNone];
        [encoder setViewport:MTLViewport{0, 0, 32, 24, 0, 1}];
        [encoder setVisibilityResultMode:mode offset:group.slot * 8];
        for (const auto &probe : group.probes) {
            Constants constants = {probe.depth, probe.discard};
            [encoder setScissorRect:probe.scissor];
            [encoder setStencilReferenceValue:probe.stencil];
            [encoder setVertexBytes:&constants length:sizeof(constants) atIndex:0];
            [encoder setFragmentBytes:&constants length:sizeof(constants) atIndex:0];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        }
        if (disabledSlot != NSNotFound) {
            require(disabledSlot < 8 && validRegion(results.length, disabledSlot * 8), @"Invalid disabled visibility offset");
            [encoder setVisibilityResultMode:MTLVisibilityResultModeDisabled offset:disabledSlot * 8];
        }
        [encoder endEncoding];
        if (separateCommands) { complete(command); command = [queue commandBuffer]; }
    }
    if (!separateCommands) complete(command);
    NSMutableArray *values = [NSMutableArray new], *slots = [NSMutableArray new];
    uint64_t words[8]; memcpy(words, results.contents, sizeof(words));
    bool untouched = true;
    for (NSUInteger slot = 0; slot < 8; slot++) {
        [values addObject:@(words[slot])];
        if (initial[slot] == canary && slot != disabledSlot && words[slot] != canary) untouched = false;
    }
    for (const auto &group : groups) [slots addObject:@(group.slot)];
    return @{ @"name":name, @"mode":@(mode), @"accumulate":@(accumulate),
        @"separate_command_buffers":@(separateCommands), @"encoder_count":@(groups.size()),
        @"slots":slots, @"words":values, @"untouched_slot_canaries":@(untouched) };
}
static std::vector<uint8_t> plane(bool depthPlane) {
    constexpr NSUInteger row = 256;
    NSUInteger bpp = depthPlane ? 4 : 1;
    id<MTLBuffer> buffer = [device newBufferWithLength:row * 24 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> command = [queue commandBuffer];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    [blit copyFromTexture:depth sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
        sourceSize:MTLSizeMake(32, 24, 1) toBuffer:buffer destinationOffset:0
        destinationBytesPerRow:row destinationBytesPerImage:row * 24
        options:depthPlane ? MTLBlitOptionDepthFromDepthStencil : MTLBlitOptionStencilFromDepthStencil];
    [blit endEncoding]; complete(command);
    std::vector<uint8_t> result(32 * 24 * bpp);
    for (NSUInteger y = 0; y < 24; y++)
        memcpy(result.data() + y * 32 * bpp, (uint8_t *)buffer.contents + y * row, 32 * bpp);
    return result;
}
static void save(NSString *folder, NSString *name, const std::vector<uint8_t> &bytes) {
    require([[NSData dataWithBytes:bytes.data() length:bytes.size()]
        writeToFile:[folder stringByAppendingPathComponent:name] atomically:YES], @"Could not save attachment evidence");
}
int main(int argc, const char **argv) { @autoreleasepool {
    require(argc == 2, @"Usage: visibility_validate OUTPUT");
    NSString *folder = @(argv[1]);
    device = MTLCreateSystemDefaultDevice(); require(device != nil, @"No native Metal device");
    queue = [device newCommandQueue]; require(queue != nil, @"No native Metal command queue");
    NSString *source = @R"MSL(
#include <metal_stdlib>
using namespace metal;
struct C { float depth; uint discard; };
struct V { float4 position [[position]]; };
vertex V vertex_probe(uint i [[vertex_id]], constant C &c [[buffer(0)]]) {
    const float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)};
    return {float4(p[i],c.depth,1)};
}
fragment float4 fragment_probe(constant C &c [[buffer(0)]]) {
    if (c.discard) discard_fragment();
    return float4(1);
}
)MSL";
    NSError *error = nil; MTLCompileOptions *options = [MTLCompileOptions new];
    options.preserveInvariance = YES;
    if (@available(macOS 15.0, *)) { options.mathMode = MTLMathModeSafe; options.mathFloatingPointFunctions = MTLMathFloatingPointFunctionsPrecise; }
    else {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        options.fastMathEnabled = NO;
#pragma clang diagnostic pop
    }
    id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
    require(library != nil, error.localizedDescription ?: @"Probe shader compilation failed");
    MTLRenderPipelineDescriptor *p = [MTLRenderPipelineDescriptor new];
    p.vertexFunction = [library newFunctionWithName:@"vertex_probe"];
    p.fragmentFunction = [library newFunctionWithName:@"fragment_probe"];
    p.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
    p.colorAttachments[0].writeMask = MTLColorWriteMaskNone;
    p.depthAttachmentPixelFormat = p.stencilAttachmentPixelFormat = MTLPixelFormatDepth32Float_Stencil8;
    pipeline = [device newRenderPipelineStateWithDescriptor:p error:&error];
    require(pipeline != nil, error.localizedDescription ?: @"Visibility pipeline failed");
    MTLDepthStencilDescriptor *d = [MTLDepthStencilDescriptor new];
    d.depthCompareFunction = MTLCompareFunctionLessEqual; d.depthWriteEnabled = NO;
    MTLStencilDescriptor *s = [MTLStencilDescriptor new];
    s.stencilCompareFunction = MTLCompareFunctionEqual; s.readMask = 255; s.writeMask = 0;
    s.stencilFailureOperation = s.depthFailureOperation = s.depthStencilPassOperation = MTLStencilOperationKeep;
    d.frontFaceStencil = d.backFaceStencil = s; state = [device newDepthStencilStateWithDescriptor:d];
    require(state != nil, @"Visibility depth/stencil state failed");
    MTLTextureDescriptor *t = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:32 height:24 mipmapped:NO];
    t.usage = MTLTextureUsageRenderTarget; t.storageMode = MTLStorageModeShared;
    color = [device newTextureWithDescriptor:t];
    t.pixelFormat = MTLPixelFormatDepth32Float_Stencil8; t.storageMode = MTLStorageModePrivate;
    depth = [device newTextureWithDescriptor:t]; require(color && depth, @"Visibility targets failed");
    std::vector<uint8_t> rgba(32 * 24 * 4);
    for (NSUInteger i = 0; i < 32 * 24; i++) { rgba[i * 4] = 33; rgba[i * 4 + 1] = 44; rgba[i * 4 + 2] = 55; rgba[i * 4 + 3] = 66; }
    [color replaceRegion:MTLRegionMake2D(0, 0, 32, 24) mipmapLevel:0 withBytes:rgba.data() bytesPerRow:128];
    id<MTLCommandBuffer> clear = [queue commandBuffer];
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.depthAttachment.texture = pass.stencilAttachment.texture = depth;
    pass.depthAttachment.loadAction = pass.stencilAttachment.loadAction = MTLLoadActionClear;
    pass.depthAttachment.storeAction = pass.stencilAttachment.storeAction = MTLStoreActionStore;
    pass.depthAttachment.clearDepth = .5; pass.stencilAttachment.clearStencil = 7;
    [[clear renderCommandEncoderWithDescriptor:pass] endEncoding]; complete(clear);
    require(validRegion(64, 0) && validRegion(64, 8) && validRegion(64, 56) &&
            !validRegion(64, 4) && !validRegion(64, 60) && !validRegion(64, 64), @"Host visibility offset guard failed");
    Probe visible, occluded; occluded.depth = .75f;
    Probe partial; partial.scissor = {4, 5, 7, 3};
    Probe stencilReject; stencilReject.stencil = 6;
    Probe discarded; discarded.discard = 1;
    NSMutableArray *cases = [NSMutableArray new];
    [cases addObject:run(@"boolean-visible", MTLVisibilityResultModeBoolean, false, {{1,{visible}}})];
    [cases addObject:run(@"boolean-depth-occluded", MTLVisibilityResultModeBoolean, false, {{1,{occluded}}})];
    [cases addObject:run(@"counting-visible", MTLVisibilityResultModeCounting, false, {{1,{visible}}})];
    [cases addObject:run(@"counting-partial-scissor", MTLVisibilityResultModeCounting, false, {{1,{partial}}})];
    [cases addObject:run(@"counting-stencil-rejected", MTLVisibilityResultModeCounting, false, {{1,{stencilReject}}})];
    [cases addObject:run(@"counting-fragment-discard", MTLVisibilityResultModeCounting, false, {{1,{discarded}}})];
    [cases addObject:run(@"counting-two-draws-one-encoder", MTLVisibilityResultModeCounting, false, {{1,{visible,visible}}})];
    [cases addObject:run(@"boolean-visible-then-occluded-one-encoder", MTLVisibilityResultModeBoolean, false, {{1,{visible,occluded}}})];
    [cases addObject:run(@"counting-reset-visible-then-occluded-two-encoders", MTLVisibilityResultModeCounting, false, {{1,{visible}},{1,{occluded}}})];
    [cases addObject:run(@"counting-reset-two-visible-two-encoders", MTLVisibilityResultModeCounting, false, {{1,{visible}},{1,{visible}}})];
    [cases addObject:run(@"counting-separate-offsets-two-encoders", MTLVisibilityResultModeCounting, false, {{1,{visible}},{2,{partial}}})];
    NSArray *diagnostics = @[run(@"disabled-other-offset-reset-control", MTLVisibilityResultModeCounting,
                                 false, {{1,{visible}}}, false, 0)];
    bool accumulateAvailable = false;
    if (@available(macOS 26.0, *)) accumulateAvailable = [device supportsFamily:MTLGPUFamilyApple7];
    if (accumulateAvailable) {
        [cases addObject:run(@"counting-accumulate-two-visible-two-encoders", MTLVisibilityResultModeCounting, true, {{1,{visible}},{1,{visible}}})];
        [cases addObject:run(@"boolean-accumulate-visible-then-occluded-two-encoders", MTLVisibilityResultModeBoolean, true, {{1,{visible}},{1,{occluded}}})];
        [cases addObject:run(@"counting-accumulate-two-command-buffers", MTLVisibilityResultModeCounting, true, {{1,{visible}},{1,{partial}}}, true)];
    }
    [color getBytes:rgba.data() bytesPerRow:128 fromRegion:MTLRegionMake2D(0, 0, 32, 24) mipmapLevel:0];
    save(folder, @"color.rgba8", rgba); save(folder, @"depth.float32", plane(true)); save(folder, @"stencil.uint8", plane(false));
    NSDictionary *result = @{ @"schema_version":@1, @"kind":@"native_metal_visibility_fixture", @"gpu_completed":@YES,
        @"device":device.name, @"os_version":NSProcessInfo.processInfo.operatingSystemVersionString,
        @"accumulate_api_tested":@(accumulateAvailable), @"synthetic_only":@YES,
        @"offset_guard_tests_passed":@YES, @"cases":cases, @"diagnostics":diagnostics,
        @"width":@32, @"height":@24, @"depth_format":@"depth32float_stencil8" };
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
    require(data && [data writeToFile:[folder stringByAppendingPathComponent:@"gpu-result.json"] atomically:YES], @"Could not save GPU result");
    printf("%s\n", [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    return 0;
} }
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def prepare(output):
    require(not output.exists(), 'Preserve existing fixture evidence; use a new output directory')
    output.mkdir(parents=True)
    sdk = Path(subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip())
    paths = [Path(__file__).resolve(), ROOT/'port/linux/src/d3d8_gl.c',
             sdk/'System/Library/Frameworks/Metal.framework/Headers/MTLRenderPass.h',
             sdk/'System/Library/Frameworks/Metal.framework/Headers/MTLRenderCommandEncoder.h']
    sources = {str(path): digest(path) for path in paths}
    source, runner = output/'visibility_validate.mm', output/'visibility_validate'
    source.write_text(SOURCE)
    command = ['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-O2', '-mmacosx-version-min=13.0',
               str(source), '-framework', 'Foundation', '-framework', 'Metal', '-o', str(runner)]
    result = subprocess.run(command, capture_output=True, text=True)
    (output/'build.log').write_text(result.stdout+result.stderr)
    require(result.returncode == 0, 'Visibility fixture build failed; see build.log')
    require(sources == {str(path): digest(path) for path in paths}, 'Fixture sources changed during preparation')
    original = ROOT/'build/metal-reference-20261004/ordered-frame-runtime/run/saves/metal-frames/frame420/captured_frame.json'
    context = None
    if original.is_file():
        frame = json.loads(original.read_bytes())
        event = next(e for e in frame['events'] if e.get('draw') == 'draw-0036.json')
        raw = frame['draws'][event['draw']]
        context = dict(file=str(original), sha256=digest(original), event=event,
                       source_render_state=raw['render_state_d3d'], executed_by_this_fixture=False)
    manifest = dict(schema_version=1, kind='metal_visibility_fixture_preparation', sources=sources,
                    generated_source=dict(file=str(source), sha256=digest(source)),
                    runner=dict(file=str(runner), sha256=digest(runner)), build_command=command,
                    original_query36_context=context,
                    policy_sources=[
                        'https://developer.apple.com/documentation/metal/mtlvisibilityresultmode/counting',
                        'https://developer.apple.com/documentation/metal/mtlvisibilityresulttype',
                        'https://developer.apple.com/documentation/metal/mtlrendercommandencoder/setvisibilityresultmode(_:offset:)'],
                    limits=['Synthetic API tests only; original query36 geometry and generated shaders are not executed.',
                            'Every synthetic result waits for GPU completion; original nonblocking cached CPU-result timing is unverified.',
                            'No invalid unaligned Metal commands are submitted; host alignment/range guards are tested separately.'])
    json_write(output/'preparation.json', manifest)
    return manifest


def verify(output):
    manifest = json.loads((output/'preparation.json').read_bytes())
    for name, expected in manifest['sources'].items():
        require(digest(Path(name)) == expected, 'Visibility fixture source provenance is stale')
    for field in ('generated_source', 'runner'):
        require(digest(Path(manifest[field]['file'])) == manifest[field]['sha256'], 'Visibility fixture runner/source changed')
    context = manifest['original_query36_context']
    if context:
        require(digest(Path(context['file'])) == context['sha256'], 'Original query36 context changed')
    raw = json.loads((output/'gpu-result.json').read_bytes())
    require(raw.get('gpu_completed') is True and raw.get('synthetic_only') is True and
            raw.get('offset_guard_tests_passed') is True, 'Visibility GPU fixture is incomplete')
    counts = {
        'boolean-visible': True, 'boolean-depth-occluded': False,
        'counting-visible': 768, 'counting-partial-scissor': 21,
        'counting-stencil-rejected': 0, 'counting-fragment-discard': 0,
        'counting-two-draws-one-encoder': 1536,
        'boolean-visible-then-occluded-one-encoder': True,
        'counting-reset-visible-then-occluded-two-encoders': 0,
        'counting-reset-two-visible-two-encoders': 768,
        'counting-separate-offsets-two-encoders': {1: 768, 2: 21}}
    if raw['accumulate_api_tested']:
        counts.update({'counting-accumulate-two-visible-two-encoders': 1536,
                       'boolean-accumulate-visible-then-occluded-two-encoders': True,
                       'counting-accumulate-two-command-buffers': 789})
    require({case['name'] for case in raw['cases']} == set(counts), 'Visibility fixture cases are missing or changed')
    for case in raw['cases']:
        expected = counts[case['name']]
        if isinstance(expected, dict):
            require(all(case['words'][slot] == count for slot, count in expected.items()),
                    'Visibility per-encoder offset preservation differs: '+case['name'])
        else:
            value = case['words'][case['slots'][-1]]
            require((bool(value) == expected) if type(expected) is bool else value == expected,
                    f'Visibility GPU result differs: {case["name"]}: {value} versus {expected}')
        require(case['untouched_slot_canaries'] is True, 'Visibility result overwrote an unused aligned slot')
    control = raw['diagnostics'][0]
    require(control['name'] == 'disabled-other-offset-reset-control' and
            control['words'][1] == 768 and control['words'][0] in (0, 0x1122334455667788) and
            control['untouched_slot_canaries'] is True,
            'Disabled-offset diagnostic changed an active query or another slot')
    planes = [('color.rgba8', bytes([33, 44, 55, 66])*768),
              ('depth.float32', struct.pack('<f', .5)*768), ('stencil.uint8', bytes([7])*768)]
    for name, expected in planes:
        require((output/name).read_bytes() == expected, 'Visibility query mutated original attachments: '+name)
    report = dict(schema_version=1, kind='metal_visibility_fixture_validation', complete=True,
                  device=raw['device'], os_version=raw['os_version'], cases=len(counts),
                  accumulate_api_tested=raw['accumulate_api_tested'],
                  attachments_unchanged=True, output_slot_canaries_preserved=True,
                  counting_and_boolean_results_verified=True,
                  disabled_other_offset_cleared_on_tested_device=control['words'][0] == 0,
                  original_query36_executed=False, original_cpu_result_timing_verified=False,
                  preparation_sha256=digest(output/'preparation.json'),
                  gpu_result_sha256=digest(output/'gpu-result.json'),
                  attachment_sha256={name:digest(output/name) for name, _ in planes},
                  limits=manifest['limits'])
    json_write(output/'validation.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if args.verify:
        result = verify(output)
    else:
        manifest = prepare(output)
        if args.prepare:
            result = dict(prepared=True, runner=manifest['runner']['file'], output=str(output))
        else:
            subprocess.run([manifest['runner']['file'], str(output)], check=True,
                           stdout=(output/'gpu.log').open('w'))
            result = verify(output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
