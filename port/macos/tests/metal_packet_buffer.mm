/* Exercise production packet ownership across synchronous GPU submissions. */
#include "../host/host_metal.mm"
#include <cstdio>
#include <cstdarg>
#include <stdexcept>
#include <string>
extern "C" {
struct host_guest_image host_image;
void *host_sdl_native_metal_layer(uint32_t window) { (void)window; return nullptr; }
void host_sdl_native_metal_release(void) {}
int host_linux_errno(int value) { return value; }
void host_logf(int priority,const char *format,...) {
    (void)priority; va_list args; va_start(args,format); vfprintf(stderr,format,args); va_end(args); fputc('\n',stderr);
}
}
static void require(bool condition,const char *message) { if(!condition) throw std::runtime_error(message); }
static constexpr uint32_t base = 0x88000000u, packetAddress = base + 16384u;
static const std::string source = R"MSL(#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; };
vertex V xgpu_vertex(uint id [[vertex_id]]) {
    const float2 p[3] = {float2(-1,-1),float2(3,-1),float2(-1,3)};
    return {float4(p[id],0,1)};
}
fragment float4 xgpu_fragment(constant float4 &color [[buffer(0)]]) { return color; }
)MSL";
struct Packet {
    std::vector<uint8_t> bytes = std::vector<uint8_t>(sizeof(halo_metal_packet),0);
    uint64_t sequence;
    uint32_t commands = 0;
    explicit Packet(uint64_t value):sequence(value) {}
    template<class Command> void append(Command command) {
        command.command.byte_size = sizeof(command);
        size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++;
    }
    uint32_t payload(const void *data,size_t size) {
        bytes.resize((bytes.size() + 15u) & ~size_t(15u),0);
        uint32_t offset = (uint32_t)bytes.size(); bytes.resize(bytes.size() + size,0);
        if (data) memcpy(bytes.data() + offset,data,size);
        return offset;
    }
    void program() {
        halo_metal_program command{}; command.command.opcode = HALO_METAL_CREATE_PROGRAM;
        command.resource = {1,1}; size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        command.vertex_source_offset = payload(source.data(),source.size()); command.vertex_source_size = (uint32_t)source.size();
        command.fragment_source_offset = payload(source.data(),source.size()); command.fragment_source_size = (uint32_t)source.size();
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); command.command.byte_size = (uint32_t)(bytes.size() - start);
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++;
    }
    void draw(uint8_t red,size_t padding = 0,bool invalidSlice = false) {
        halo_metal_draw command{}; command.command.opcode = HALO_METAL_DRAW;
        command.program = {1,1}; command.color = {1,1}; command.vertex_count = command.index_count = 3;
        command.primitive = MTLPrimitiveTypeTriangle;
        auto &s = command.state; s.color_write_mask = 15;
        s.blend_source = s.blend_destination = s.blend_operation = 1;
        s.depth_compare = s.stencil_compare = 8; s.stencil_fail = s.stencil_depth_fail = s.stencil_pass = 1;
        s.viewport[2] = s.viewport[3] = 4; s.viewport[5] = 1; s.scissor[2] = s.scissor[3] = 4;
        size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        command.vertices_offset = payload(nullptr,3 * HaloMetalVertexStride);
        const uint32_t indices[] = {0,1,2}; command.indices_offset = payload(indices,sizeof(indices));
        command.vertex_uniforms_offset = payload(nullptr,HaloMetalVertexUniformSize);
        command.pixel_uniforms_offset = payload(nullptr,HaloMetalPixelUniformSize);
        const float color[] = {red / 255.0f,22.0f / 255.0f,33.0f / 255.0f,1};
        memcpy(bytes.data() + command.pixel_uniforms_offset,color,sizeof(color));
        bytes.resize((bytes.size() + padding + 7u) & ~size_t(7u),0);
        command.command.byte_size = (uint32_t)(bytes.size() - start);
        if (invalidSlice) command.pixel_uniforms_offset = 32768; // Fits a warm buffer, outside this command.
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++;
    }
    void invalid() {
        const halo_metal_command command{UINT32_MAX,sizeof(halo_metal_command)};
        size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++;
    }
    void copy_to_guest() {
        const halo_metal_packet header{HALO_METAL_MAGIC,HALO_METAL_ABI_VERSION,(uint32_t)bytes.size(),commands,sequence};
        memcpy(bytes.data(),&header,sizeof(header)); memcpy(guest_pointer(packetAddress),bytes.data(),bytes.size());
    }
    int submit() {
        copy_to_guest();
        return host_metal_submit(packetAddress,(uint32_t)bytes.size(),base,sizeof(halo_metal_reply));
    }
};
static void initialize() {
    require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,"device initialization");
    context.metrics.enabled = true;
    Packet setup(1); setup.program();
    setup.append(halo_metal_create{{HALO_METAL_CREATE_TEXTURE,0},{1,1},HALO_METAL_RGBA8,4,4,0});
    halo_metal_clear clear{}; clear.command.opcode = HALO_METAL_CLEAR; clear.color = {1,1};
    clear.planes = HALO_METAL_COLOR; clear.width = clear.height = 4; setup.append(clear);
    require(setup.submit() == HALO_METAL_OK,"setup packet");
}
static void readback(uint8_t red) {
    require(host_metal_readback(1,1,HALO_METAL_COLOR,base + 512,64,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,"color readback");
    const auto *pixels = (const uint8_t *)guest_pointer(base + 512);
    for (size_t i = 0; i < 16; i++) require(pixels[i*4] == red && pixels[i*4+1] == 22 &&
        pixels[i*4+2] == 33 && pixels[i*4+3] == 255,"unchanged original output bytes");
}
static void valid_draw(uint64_t sequence,uint8_t red,size_t padding = 0) {
    Packet packet(sequence); packet.draw(red,padding); require(packet.submit() == HALO_METAL_OK,"draw packet"); readback(red);
}
int main(int argc,char **argv) { @autoreleasepool {
    try {
        require(host_memory_initialize(base,64u * 1024u * 1024u) == 0,"guest memory"); initialize();
        if (argc == 2 && std::string(argv[1]) == "benchmark") {
            // Warm the same pipeline, then time real synchronous packet submits.
            for (uint64_t i = 2; i < 7; i++) {
                Packet p(i); for (unsigned j = 0; j < 32; j++) p.draw(11,j == 31 ? 512u*1024u : 0);
                require(p.submit() == 0,"warm draw");
            }
            context.metrics.packet_buffers = 0; std::vector<uint64_t> samples;
            for (uint64_t i = 7; i < 107; i++) {
                Packet p(i); for (unsigned j = 0; j < 32; j++) p.draw((uint8_t)(11 + (i & 1)),j == 31 ? 512u*1024u : 0);
                auto started = std::chrono::steady_clock::now(); require(p.submit() == 0,"timed draw");
                samples.push_back((uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::steady_clock::now() - started).count());
            }
            readback(11); std::sort(samples.begin(),samples.end());
            printf("{\"complete\":true,\"samples\":100,\"median_ns\":%llu,\"p95_ns\":%llu,\"packet_allocations\":%llu}\n",
                (unsigned long long)samples[50],(unsigned long long)samples[94],(unsigned long long)context.metrics.packet_buffers);
        } else {
            valid_draw(2,11); valid_draw(3,44); require(context.metrics.packet_buffers == 1,"warm reuse allocation count");
            Packet rejected(4); rejected.draw(99); rejected.invalid();
            require(rejected.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 3 && context.completed == 3,"atomic late rejection");
            readback(44); valid_draw(4,55);
            valid_draw(5,66,5u*1024u*1024u); valid_draw(6,77);
            require(context.metrics.packet_buffers == 2 && context.draw_input_buffer.length == 8u*1024u*1024u,
                "growth beyond 4 MiB is retained");
            valid_draw(7,88,9u*1024u*1024u); valid_draw(8,99,20000);
            require(context.metrics.packet_buffers == 3 && context.draw_input_buffer.length == 16u*1024u*1024u,
                "bounded growth to 16 MiB and smaller reuse");
            Packet extent(9); extent.draw(100);
            valid_draw(9,100,16u*1024u*1024u-extent.bytes.size());
            require(context.metrics.packet_buffers == 3,"exact retained capacity reuses storage");
            valid_draw(10,111,17u*1024u*1024u);valid_draw(11,122);
            require(context.metrics.packet_buffers == 4 && context.draw_input_buffer.length == 16u*1024u*1024u,
                "oversized buffer is temporary and leaves bounded retention");
            Packet outside(12); outside.draw(133,0,true);
            require(outside.submit() == HALO_METAL_INVALID && context.submitted == 11,"retained slack does not extend command ranges"); readback(122);
            valid_draw(12,144);
            host_metal_shutdown(); initialize(); valid_draw(2,155);
            require(context.metrics.packet_buffers == 1,"shutdown releases prior storage");
            printf("{\"complete\":true,\"changing_payload_bytes\":true,\"atomic_rejection\":true,\"bounded_reuse\":true,\"retained_16mib\":true,\"exact_capacity\":true,\"growth_and_oversize\":true,\"command_ranges\":true,\"shutdown_reset\":true}\n");
        }
        host_metal_shutdown(); return 0;
    } catch (const std::exception &error) { fprintf(stderr,"%s\n",error.what()); return 1; }
} }
