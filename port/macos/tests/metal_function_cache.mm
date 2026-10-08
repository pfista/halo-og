/* Headless compiler/atomic-preflight proof. Including the production backend
 * gives this test visibility of its private cache; no test API ships in Halo. */
#include "../host/host_metal.mm"
#include <cstdio>
#include <cstdarg>
#include <stdexcept>
extern "C" {
struct host_guest_image host_image;
void *host_sdl_native_metal_layer(uint32_t window) { (void)window; return nullptr; }
void host_sdl_native_metal_release(void) {}
int host_linux_errno(int value) { return value; }
void host_logf(int priority,const char *format,...) {
    (void)priority;va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);fputc('\n',stderr);
}
}
static void require(bool condition,const char *message) { if(!condition)throw std::runtime_error(message); }
static constexpr uint32_t base=0x88000000u, packetAddress=base+16384u, replyAddress=base, resultAddress=base+512u;
static const std::string source=R"MSL(#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; };
vertex V xgpu_vertex(uint id [[vertex_id]]) {
    const float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};
    return {float4(p[id],0,1)};
}
fragment float4 xgpu_fragment() { return float4(11.0f/255.0f,22.0f/255.0f,33.0f/255.0f,1); }
)MSL";

struct Packet {
    std::vector<uint8_t> bytes=std::vector<uint8_t>(sizeof(halo_metal_packet),0);
    uint64_t sequence;
    uint32_t commands=0;
    explicit Packet(uint64_t number):sequence(number) {}
    template<class Command> void append(Command value) {
        value.command.byte_size=sizeof(value);size_t offset=bytes.size();bytes.resize(offset+sizeof(value),0);
        memcpy(bytes.data()+offset,&value,sizeof(value));commands++;
    }
    void program(uint32_t id,uint32_t generation,const std::string &msl) {
        program(id,generation,msl,msl);
    }
    void program(uint32_t id,uint32_t generation,const std::string &vertexSource,const std::string &fragmentSource,
                 uint32_t vertexContract=0,uint32_t fragmentContract=0) {
        halo_metal_program value{};value.command.opcode=HALO_METAL_CREATE_PROGRAM;
        value.vertex_compiler_contract=vertexContract;value.fragment_compiler_contract=fragmentContract;
        value.resource={id,generation};size_t start=bytes.size();bytes.resize(start+sizeof(value),0);
        bytes.resize((bytes.size()+15u)&~size_t(15u),0);value.vertex_source_offset=(uint32_t)bytes.size();
        value.vertex_source_size=(uint32_t)vertexSource.size();bytes.insert(bytes.end(),vertexSource.begin(),vertexSource.end());
        bytes.resize((bytes.size()+15u)&~size_t(15u),0);value.fragment_source_offset=(uint32_t)bytes.size();
        value.fragment_source_size=(uint32_t)fragmentSource.size();bytes.insert(bytes.end(),fragmentSource.begin(),fragmentSource.end());
        bytes.resize((bytes.size()+7u)&~size_t(7u),0);value.command.byte_size=(uint32_t)(bytes.size()-start);
        memcpy(bytes.data()+start,&value,sizeof(value));commands++;
    }
    void visibility(uint32_t opcode) { append(halo_metal_visibility{{opcode,0},{200,1}}); }
    void target() {
        append(halo_metal_create{{HALO_METAL_CREATE_TEXTURE,0},{1,1},HALO_METAL_RGBA8,4,4,0});
        halo_metal_clear clear{};clear.command.opcode=HALO_METAL_CLEAR;clear.color={1,1};
        clear.planes=HALO_METAL_COLOR;clear.width=clear.height=4;append(clear);
    }
    void draw(uint32_t programId=1) {
        halo_metal_draw value{};value.command.opcode=HALO_METAL_DRAW;value.program={programId,1};value.color={1,1};
        value.vertex_count=value.index_count=3;value.primitive=MTLPrimitiveTypeTriangle;
        auto &s=value.state;s.color_write_mask=15;s.blend_source=s.blend_destination=s.blend_operation=1;
        s.depth_compare=s.stencil_compare=8;s.stencil_fail=s.stencil_depth_fail=s.stencil_pass=1;
        s.viewport[2]=s.viewport[3]=4;s.viewport[5]=1;s.scissor[2]=s.scissor[3]=4;
        size_t start=bytes.size();bytes.resize(start+sizeof(value),0);
        auto payload=[&](size_t count){bytes.resize((bytes.size()+15u)&~size_t(15u),0);
            uint32_t offset=(uint32_t)bytes.size();bytes.resize(bytes.size()+count,0);return offset;};
        value.vertices_offset=payload(3*HaloMetalVertexStride);value.indices_offset=payload(12);
        const uint32_t indices[]={0,1,2};memcpy(bytes.data()+value.indices_offset,indices,sizeof(indices));
        value.vertex_uniforms_offset=payload(HaloMetalVertexUniformSize);value.pixel_uniforms_offset=payload(HaloMetalPixelUniformSize);
        bytes.resize((bytes.size()+7u)&~size_t(7u),0);value.command.byte_size=(uint32_t)(bytes.size()-start);
        memcpy(bytes.data()+start,&value,sizeof(value));commands++;
    }
    void invalid() {
        halo_metal_command value{0xffffffffu,sizeof(halo_metal_command)};
        size_t offset=bytes.size();bytes.resize(offset+sizeof(value),0);memcpy(bytes.data()+offset,&value,sizeof(value));commands++;
    }
    int submit() {
        halo_metal_packet header{HALO_METAL_MAGIC,HALO_METAL_ABI_VERSION,(uint32_t)bytes.size(),commands,sequence};
        memcpy(bytes.data(),&header,sizeof(header));memcpy(guest_pointer(packetAddress),bytes.data(),bytes.size());
        return host_metal_submit(packetAddress,(uint32_t)bytes.size(),replyAddress,sizeof(halo_metal_reply));
    }
};
static halo_metal_reply replyValue() { halo_metal_reply result;memcpy(&result,guest_pointer(replyAddress),sizeof(result));return result; }
static std::vector<uint8_t> render(id<MTLFunction> vertex,id<MTLFunction> fragment) {
    auto descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:4 height:4 mipmapped:NO];
    descriptor.usage=MTLTextureUsageRenderTarget;descriptor.storageMode=MTLStorageModeShared;
    auto texture=[context.device newTextureWithDescriptor:descriptor];require(texture!=nil,"render texture");
    auto pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=texture;
    pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    auto command=[context.queue commandBuffer];auto encoder=[command renderCommandEncoderWithDescriptor:pass];
    require(encoder!=nil,"controlled clear encoder");[encoder endEncoding];
    auto input=[context.device newBufferWithLength:4096 options:MTLResourceStorageModeShared];require(input!=nil,"controlled inputs");
    memset(input.contents,0,4096);const uint32_t indices[]={0,1,2};memcpy((uint8_t *)input.contents+768,indices,sizeof(indices));
    HaloMetalDraw draw;draw.vertexFunction=vertex;draw.fragmentFunction=fragment;draw.color=texture;
    draw.vertices=draw.indices=draw.vertexUniforms=draw.pixelUniforms=input;draw.indexOffset=768;
    draw.vertexCount=draw.indexCount=3;draw.state.color_write_mask=15;
    draw.state.blend_source=draw.state.blend_destination=draw.state.blend_operation=1;
    draw.state.depth_compare=draw.state.stencil_compare=8;
    draw.state.stencil_fail=draw.state.stencil_depth_fail=draw.state.stencil_pass=1;
    draw.state.viewport[2]=draw.state.viewport[3]=4;draw.state.viewport[5]=1;
    draw.state.scissor[2]=draw.state.scissor[3]=4;
    NSError *error=nil;require([context.draw_encoder encodeDraw:draw commandBuffer:command error:&error],"controlled original draw");
    [command commit];[command waitUntilCompleted];require(command.status==MTLCommandBufferStatusCompleted,"controlled completion");
    std::vector<uint8_t> result(64);[texture getBytes:result.data() bytesPerRow:16 fromRegion:MTLRegionMake2D(0,0,4,4) mipmapLevel:0];
    return result;
}
int main() { @autoreleasepool {
    try {
        require(host_memory_initialize(base,1024u*1024u)==0,"guest memory");
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"Metal device");
        context.metrics.enabled=true;
        Packet first(1);first.program(1,1,source);first.program(2,1,source);
        first.append(halo_metal_create_visibility{{HALO_METAL_CREATE_VISIBILITY,0},{200,1},HALO_METAL_VISIBILITY_COUNTING,0});
        first.visibility(HALO_METAL_BEGIN_VISIBILITY);first.visibility(HALO_METAL_END_VISIBILITY);
        require(first.submit()==0,"first programs");
        require(context.metrics.shader_compile_misses==2 && context.metrics.shader_compile_hits==2 &&
                context.metrics.shader_compile_pairs==1 && context.compiled_functions.size()==2,"staged source reuse/bounded pair");
        auto vertex=context.programs.at(1).vertex;auto fragment=context.programs.at(1).fragment;
        require(vertex==context.programs.at(2).vertex && fragment==context.programs.at(2).fragment,"identical functions");
        auto expected=render(vertex,fragment);
        for(size_t i=0;i<16;i++)require(expected[i*4]==11 && expected[i*4+1]==22 && expected[i*4+2]==33 && expected[i*4+3]==255,"controlled original bytes");
        // Test-only inspection of the encoder's retained PSO cache: no public
        // production accessor or allocation counter is needed for this proof.
        NSDictionary *pipelines=[context.draw_encoder valueForKey:@"pipelines"];
        require(pipelines.count==1,"controlled warm pipeline count");id warmPipeline=pipelines.allValues.firstObject;
        Packet second(2);second.program(3,1,source);require(second.submit()==0,"cached later packet");
        require(context.metrics.shader_compile_hits==4 && context.metrics.shader_compile_misses==2 &&
                context.metrics.shader_compile_pairs==1 && context.programs.at(3).vertex==vertex &&
                context.programs.at(3).fragment==fragment,"published source reuse");

        // Either single-stage cache miss must keep one serial compiler call.
        // Private staged variants preserve pixels without publishing cache
        // entries or programs into the live context used by rejection checks.
        {
            Prepared mixed;const auto pairs=context.metrics.shader_compile_pairs;
            const auto misses=context.metrics.shader_compile_misses,hits=context.metrics.shader_compile_hits;
            Packet fragmentMiss(0);fragmentMiss.program(80,1,source,source+"\n// fragment-only miss\n");
            auto fragmentOnly=compile_program(mixed,fragmentMiss.bytes,record<halo_metal_program>(fragmentMiss.bytes,sizeof(halo_metal_packet)));
            require(fragmentOnly.vertex==vertex && fragmentOnly.fragment!=fragment,"fragment miss changed the cached vertex");
            Packet vertexMiss(0);vertexMiss.program(81,1,source+"\n// vertex-only miss\n",source);
            auto vertexOnly=compile_program(mixed,vertexMiss.bytes,record<halo_metal_program>(vertexMiss.bytes,sizeof(halo_metal_packet)));
            require(vertexOnly.vertex!=vertex && vertexOnly.fragment==fragment,"vertex miss changed the cached fragment");
            require(context.metrics.shader_compile_pairs==pairs && context.metrics.shader_compile_misses==misses+2 &&
                context.metrics.shader_compile_hits==hits+2 && mixed.compiled_functions.size()==2,"single-stage misses launched an async pair");
            require(render(fragmentOnly.vertex,fragmentOnly.fragment)==expected && render(vertexOnly.vertex,vertexOnly.fragment)==expected,
                    "single-stage compiler paths changed original pixels");
            [context.draw_encoder removePipelinesForVertexFunction:vertexOnly.vertex fragmentFunction:fragmentOnly.fragment];
        }

        const auto savedBytes=context.compiled_functions.sourceBytes();const auto savedMisses=context.metrics.shader_compile_misses;
        const std::string changed=source+"\n// distinct source bytes\n";
        Packet rejected(3);rejected.visibility(HALO_METAL_BEGIN_VISIBILITY);rejected.program(4,1,changed);
        rejected.visibility(HALO_METAL_END_VISIBILITY);rejected.invalid();
        require(rejected.submit()==HALO_METAL_UNSUPPORTED,"late unknown command rejection");
        auto failed=replyValue();
        require(failed.failed_command==3 && failed.submitted_sequence==2 && failed.completed_sequence==2 &&
                context.programs.size()==3 && !context.programs.count(4) && !context.program_generations.count(4) &&
                context.compiled_functions.size()==2 && context.compiled_functions.sourceBytes()==savedBytes &&
                context.queries.at(200).version==1 && context.queries.at(200).ended && !context.active_query.id &&
                !context.poisoned,"rejected packet published state");
        require(context.metrics.shader_compile_misses==savedMisses+2,"candidate compilation counted");
        require(host_metal_readback(200,1,HALO_METAL_VISIBILITY,resultAddress,8,replyAddress,sizeof(halo_metal_reply))==0,"prior query remains readable");
        uint64_t visible=1;memcpy(&visible,guest_pointer(resultAddress),8);require(visible==0 && replyValue().content_version==1,"prior query changed");
        Packet cachedRejection(3);cachedRejection.program(9,1,source);cachedRejection.invalid();
        require(cachedRejection.submit()==HALO_METAL_UNSUPPORTED && !context.programs.count(9) &&
                context.compiled_functions.size()==2 && context.metrics.shader_compile_misses==savedMisses+2 &&
                pipelines.count==1 && pipelines.allValues.firstObject==warmPipeline,"cache-hit rejection evicted a live pipeline");
        Packet retry(3);retry.program(4,1,changed);require(retry.submit()==0,"valid candidate retry");
        require(context.metrics.shader_compile_misses==savedMisses+4 && context.compiled_functions.size()==4,"rejected compiler entries were retained");
        Packet generation(4);generation.append(halo_metal_delete{{HALO_METAL_DELETE_PROGRAM,0},{1,1}});
        generation.program(1,2,source);require(generation.submit()==0 && context.programs.at(1).generation==2 &&
            context.programs.at(1).vertex==vertex && context.programs.at(1).fragment==fragment,"program generation semantics");
        require(pipelines.count==1 && pipelines.allValues.firstObject==warmPipeline,"shared program deletion evicted a live pipeline");

        const auto beforeFailure=context.metrics.shader_compile_misses;
        for(unsigned i=0;i<2;i++) {
            Packet bad(5);bad.program(5,1,"this is not Metal source");
            require(bad.submit()==HALO_METAL_GPU_ERROR && context.compiled_functions.size()==4 &&
                    !context.programs.count(5) && context.submitted==4 && !context.poisoned,"failed compile cache/state");
        }
        require(context.metrics.shader_compile_misses==beforeFailure+4,"failed async pair was cached or not drained/retried");
        // Lexical source checks happen before either request. Once launched,
        // a failing stage must leave successful siblings private and retryable.
        const auto isolatedCacheSize=context.compiled_functions.size();
        const auto isolatedPrograms=context.programs.size();
        auto rejectedPair=[&](const std::string &vertexSource,const std::string &fragmentSource,int status,unsigned calls) {
            const auto misses=context.metrics.shader_compile_misses,pairs=context.metrics.shader_compile_pairs;
            Packet candidate(5);candidate.program(50,1,vertexSource,fragmentSource);
            require(candidate.submit()==status && replyValue().failed_command==0 &&
                context.submitted==4 && context.completed==4 && !context.poisoned &&
                context.compiled_functions.size()==isolatedCacheSize && context.programs.size()==isolatedPrograms &&
                !context.programs.count(50) && !context.program_generations.count(50),"failed pair published compiler/program/sequence state");
            require(context.metrics.shader_compile_misses==misses+calls &&
                    context.metrics.shader_compile_pairs==pairs+(calls==2),"failed pair compiler accounting");
        };
        const std::string isolated=source+"\n// isolated failed-pair sibling\n";
        for(unsigned attempt=0;attempt<2;attempt++) {
            rejectedPair(isolated,"invalid fragment Metal source",HALO_METAL_GPU_ERROR,2);
            rejectedPair("invalid vertex Metal source",isolated,HALO_METAL_GPU_ERROR,2);
        }
        rejectedPair(isolated,std::string("\0invalid",8),HALO_METAL_INVALID,0);
        rejectedPair(isolated,std::string(1,(char)0xff),HALO_METAL_INVALID,0);
        const std::string fragmentOnly=R"MSL(#include <metal_stdlib>
using namespace metal;
fragment float4 xgpu_fragment() { return float4(0); }
)MSL";
        const std::string vertexOnly=R"MSL(#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; };
vertex V xgpu_vertex(uint id [[vertex_id]]) { return {float4(float(id))}; }
)MSL";
        rejectedPair(fragmentOnly,isolated,HALO_METAL_INVALID,2);
        rejectedPair(isolated,vertexOnly,HALO_METAL_INVALID,2);

        Prepared contracts;std::vector<uint8_t> text(source.begin(),source.end());
        const auto beforeContracts=context.metrics.shader_compile_misses;
        auto fastVertex=compile_function(contracts,text,0,(uint32_t)text.size(),true,true,true);
        require(fastVertex!=nil && compile_function(contracts,text,0,(uint32_t)text.size(),true,true,true)==fastVertex,"candidate fast vertex reuse");
        require(compile_function(contracts,text,0,(uint32_t)text.size(),true,false,false)!=nil,"invariance separation");
        require(compile_function(contracts,text,0,(uint32_t)text.size(),false,true,false)!=nil,"fast fragment separation");
        require(context.metrics.shader_compile_misses==beforeContracts+3 && contracts.compiled_functions.size()==3,"compile contracts conflated");
        require(render(context.programs.at(3).vertex,context.programs.at(3).fragment)==expected,"cached rendered bytes differ");
        context.compiled_functions.clear();Prepared uncached;
        auto uncachedVertex=compile_function(uncached,text,0,(uint32_t)text.size(),true,false,true);
        auto uncachedFragment=compile_function(uncached,text,0,(uint32_t)text.size(),false,false,true);
        require(render(uncachedVertex,uncachedFragment)==expected,"fresh rendered bytes differ");
        host_metal_shutdown();require(!context.device && context.compiled_functions.size()==0 && context.programs.empty(),"context did not reset");
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"new context");
        context.metrics.enabled=true;Packet reset(1);reset.program(1,1,source);require(reset.submit()==0 &&
            context.metrics.shader_compile_misses==2 && context.metrics.shader_compile_hits==0,"new device context used stale cache");
        require(render(context.programs.at(1).vertex,context.programs.at(1).fragment)==expected,"new context rendered bytes differ");
        host_metal_shutdown();
        NSString *folder=[NSTemporaryDirectory() stringByAppendingPathComponent:[@"halo-metal-warmup-proof-" stringByAppendingString:[NSUUID UUID].UUIDString]];
        NSString *path=[folder stringByAppendingPathComponent:@"Cache/MetalWarmup-v1.bin"];
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"learned context");
        context.metrics.enabled=true;context.draw_encoder.diagnosticsEnabled=YES;
        context.warmup_path=path;context.draw_encoder.warmupLearningEnabled=YES;
        Packet rejectedWarmup(1);rejectedWarmup.program(1,1,source);rejectedWarmup.target();rejectedWarmup.draw();rejectedWarmup.invalid();
        require(rejectedWarmup.submit()==HALO_METAL_UNSUPPORTED && context.warmup.functions.empty() &&
            context.warmup.pipelines.empty() && !context.warmup_dirty && context.submitted==0,"rejected packet learned cache entries");
        Packet learned(1);learned.program(1,1,source);learned.target();learned.draw();require(learned.submit()==0,"learn actual completed draw");
        require(context.warmup.functions.size()==2 && context.warmup.pipelines.size()==1 && context.warmup_dirty,"completed packet not learned");
        require(host_metal_readback(1,1,HALO_METAL_COLOR,resultAddress,64,replyAddress,sizeof(halo_metal_reply))==0 &&
            !memcmp(guest_pointer(resultAddress),expected.data(),64),"learned packet original pixels");
        warmup_save();require(!context.warmup_dirty && [[NSFileManager defaultManager] fileExistsAtPath:path],"atomic learned cache write");
        const auto learnedBytes=context.warmup.encode();host_metal_shutdown();
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"prewarm context");
        context.metrics.enabled=true;context.draw_encoder.diagnosticsEnabled=YES;context.warmup_path=path;warmup_initialize();
        require(context.compiled_functions.size()==2 && context.warmup.encode()==learnedBytes && context.programs.empty() &&
            context.textures.empty() && context.submitted==0 && context.draw_encoder.renderPassCount==0 &&
            context.draw_encoder.pipelineCreationCount==0 && context.metrics.shader_compile_misses==0,"warmup mutated render state or gameplay counters");
        context.draw_encoder.warmupLearningEnabled=YES;
        Packet warmed(1);warmed.program(1,1,source);warmed.target();warmed.draw();require(warmed.submit()==0,"prewarmed accepted packet");
        require(context.metrics.shader_compile_hits==2 && context.metrics.shader_compile_misses==0 &&
            context.draw_encoder.pipelineCreationCount==0 && !context.warmup_dirty,"startup function/PSO missed");
        require(host_metal_readback(1,1,HALO_METAL_COLOR,resultAddress,64,replyAddress,sizeof(halo_metal_reply))==0 &&
            !memcmp(guest_pointer(resultAddress),expected.data(),64),"prewarmed original output bytes");
        Packet failedLearn(2);failedLearn.program(2,1,source+"// rejected new source\n");failedLearn.draw(2);failedLearn.invalid();
        require(failedLearn.submit()==HALO_METAL_UNSUPPORTED && context.warmup.encode()==learnedBytes &&
            !context.warmup_dirty && context.submitted==1 && !context.programs.count(2),"rejected new variant persisted");
        // A shared fragment remains eligible through an expanded pipeline;
        // compact-only vertices and mode-unknown orphans stay lazy when off.
        const HaloMetalFunctionKey compactOnly{source+"// compact-only startup fixture\n",true,false,true};
        const HaloMetalFunctionKey orphan{source+"// orphan startup fixture\n",true,false,true};
        require(context.warmup.learn(compactOnly)==2 && context.warmup.learn(orphan)==3,"mixed warmup function fixture");
        auto compactPipeline=context.warmup.pipelines[0];compactPipeline.vertex=2;compactPipeline.compact=1;
        require(context.warmup.learn(compactPipeline),"mixed warmup pipeline fixture");
        const auto mixedBytes=context.warmup.encode();context.warmup_dirty=true;warmup_save();host_metal_shutdown();
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"disabled mixed warmup context");
        context.warmup_path=path;warmup_initialize();
        require(context.compiled_functions.size()==2 && !context.compiled_functions.find(compactOnly) &&
            !context.compiled_functions.find(orphan) && context.warmup.encode()==mixedBytes,
            "disabled compact-only or orphan startup source was compiled");
        host_metal_shutdown();
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN|HALO_METAL_ENABLE_COMPACT_VERTICES,
            replyAddress,sizeof(halo_metal_reply))==0,"enabled mixed warmup context");
        context.warmup_path=path;warmup_initialize();
        require(context.compiled_functions.size()==3 && context.compiled_functions.find(compactOnly) &&
            !context.compiled_functions.find(orphan) && context.warmup.encode()==mixedBytes,
            "enabled compact startup source or stable manifest identity was lost");
        host_metal_shutdown();require([[@"bad cache" dataUsingEncoding:NSUTF8StringEncoding] writeToFile:path atomically:YES],"corrupt fixture write");
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,replyAddress,sizeof(halo_metal_reply))==0,"corrupt cache context");
        context.metrics.enabled=true;context.warmup_path=path;warmup_initialize();
        require(context.compiled_functions.size()==0 && context.warmup.functions.empty() && !context.poisoned,"corrupt cache did not fall back");
        Packet fallback(1);fallback.program(1,1,source);fallback.target();fallback.draw();require(fallback.submit()==0 &&
            context.metrics.shader_compile_misses==2,"ordinary compile fallback");
        require(host_metal_readback(1,1,HALO_METAL_COLOR,resultAddress,64,replyAddress,sizeof(halo_metal_reply))==0 &&
            !memcmp(guest_pointer(resultAddress),expected.data(),64),"fallback original output bytes");
        host_metal_shutdown();[[NSFileManager defaultManager] removeItemAtPath:folder error:nil];
        std::printf("{\"exact_function_reuse\":true,\"compile_contract_separation\":true,\"failed_compile_retry\":true,\"atomic_packet_rejection\":true,\"shared_pipeline_retention\":true,\"device_context_reset\":true,\"identical_render_bytes\":true,\"bounded_async_pair\":true,\"single_stage_serial\":true,\"failed_pair_isolation\":true,\"lexical_validation_before_requests\":true,\"learned_startup_cache\":true,\"prewarmed_pipeline_hit\":true,\"warmup_exact_output\":true,\"rejected_warmup_isolation\":true,\"corrupt_warmup_fallback\":true,\"readback_hex\":\"");
        for(uint8_t byte:expected)std::printf("%02x",byte);std::puts("\"}");return 0;
    } catch(const std::exception &error) { std::fprintf(stderr,"Compiler cache proof: %s\n",error.what());host_metal_shutdown();return 1; }
} }
