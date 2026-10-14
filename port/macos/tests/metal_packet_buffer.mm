/* Exercise production packet ownership across synchronous GPU submissions. */
#include "../host/host_metal.mm"
#include "../include/halo_metal_vertex_input.h"
#include <cstdio>
#include <cstdarg>
#include <stdexcept>
#include <string>
#include <atomic>
#include <thread>
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
    void draw(uint8_t red,size_t padding = 0,bool invalidSlice = false,bool compact = false,bool invalidCompact = false) {
        halo_metal_draw command{}; command.command.opcode = compact ? HALO_METAL_DRAW_COMPACT : HALO_METAL_DRAW;
        command.program = {1,1}; command.color = {1,1}; command.vertex_count = command.index_count = 3;
        command.primitive = MTLPrimitiveTypeTriangle;
        auto &s = command.state; s.color_write_mask = 15;
        s.blend_source = s.blend_destination = s.blend_operation = 1;
        s.depth_compare = s.stencil_compare = 8; s.stencil_fail = s.stencil_depth_fail = s.stencil_pass = 1;
        s.viewport[2] = s.viewport[3] = 4; s.viewport[5] = 1; s.scissor[2] = s.scissor[3] = 4;
        size_t start = bytes.size(); bytes.resize(start + (compact ? sizeof(halo_metal_draw_compact) : sizeof(command)),0);
        if (compact) {
            halo_metal_compact_vertex_input input{};
            input.version = HALO_METAL_COMPACT_VERTEX_VERSION;input.vertex_count = invalidCompact ? 4 : 3;
            command.vertices_offset = payload(&input,sizeof(input));
        } else command.vertices_offset = payload(nullptr,3 * HaloMetalVertexStride);
        const uint32_t indices[] = {0,1,2}; command.indices_offset = payload(indices,sizeof(indices));
        command.vertex_uniforms_offset = payload(nullptr,HaloMetalVertexUniformSize);
        command.pixel_uniforms_offset = payload(nullptr,HaloMetalPixelUniformSize);
        const float color[] = {red / 255.0f,22.0f / 255.0f,33.0f / 255.0f,1};
        memcpy(bytes.data() + command.pixel_uniforms_offset,color,sizeof(color));
        bytes.resize((bytes.size() + padding + 7u) & ~size_t(7u),0);
        command.command.byte_size = (uint32_t)(bytes.size() - start);
        if (invalidSlice) command.pixel_uniforms_offset = 32768; // Fits a warm buffer, outside this command.
        if (compact) {
            halo_metal_draw_compact extended{command,sizeof(halo_metal_compact_vertex_input),0,0,0};
            memcpy(bytes.data()+start,&extended,sizeof(extended));
        } else memcpy(bytes.data() + start,&command,sizeof(command));
        commands++;
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
static void initialize(bool compact = false,bool async = false,bool uniforms = false,bool geometry = false) {
    require(host_metal_initialize(0,HALO_METAL_OFFSCREEN | (compact ? HALO_METAL_ENABLE_COMPACT_VERTICES : 0) |
        (async ? HALO_METAL_ENABLE_ASYNC_SUBMIT : 0) | (uniforms ? HALO_METAL_ENABLE_UNIFORM_SHARING : 0) |
        (geometry ? HALO_METAL_ENABLE_GEOMETRY_CACHE : 0),
        base,sizeof(halo_metal_reply)) == HALO_METAL_OK,"device initialization");
    halo_metal_reply reply;memcpy(&reply,guest_pointer(base),sizeof(reply));
    require(bool(reply.capabilities & HALO_METAL_CAP_COMPACT_VERTICES) == compact,"compact capability requires explicit opt-in");
    require(bool(reply.capabilities & HALO_METAL_CAP_ASYNC_SUBMIT) == async,"async capability requires explicit opt-in");
    require(bool(reply.capabilities & HALO_METAL_CAP_UNIFORM_SHARING) == uniforms,"uniform capability requires explicit opt-in");
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
struct GeometryPacket : Packet {
    using Packet::Packet;
    static std::vector<uint8_t> input() {
        halo_metal_compact_vertex_input prefix{};
        prefix.version = HALO_METAL_COMPACT_VERTEX_VERSION; prefix.vertex_count = 3; prefix.element_count = 1;
        prefix.elements[0] = {0,0x42,sizeof(prefix),16};
        const float positions[3][4] = {{-1,-1,0,1},{3,-1,0,1},{-1,3,0,1}};
        std::vector<uint8_t> result(sizeof(prefix) + sizeof(positions));
        memcpy(result.data(),&prefix,sizeof(prefix)); memcpy(result.data() + sizeof(prefix),positions,sizeof(positions));
        return result;
    }
    void geometryProgram() {
        const std::string text = R"MSL(#include <metal_stdlib>
using namespace metal;
struct V { float4 position [[position]]; };
vertex V xgpu_vertex(uint id [[vertex_id]],device const uchar *input [[buffer(1)]]) {
    return {((device const float4 *)(input + 528))[id]};
}
fragment float4 xgpu_fragment(constant float4 &color [[buffer(0)]]) { return color; }
)MSL";
        halo_metal_program command{}; command.command.opcode = HALO_METAL_CREATE_PROGRAM; command.resource = {1,1};
        const size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        command.vertex_source_offset = payload(text.data(),text.size()); command.vertex_source_size = (uint32_t)text.size();
        command.fragment_source_offset = payload(text.data(),text.size()); command.fragment_source_size = (uint32_t)text.size();
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); command.command.byte_size = (uint32_t)(bytes.size() - start);
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++;
    }
    uint32_t createGeometry(halo_metal_ref ref,bool invalidIndex = false) {
        halo_metal_create_geometry command{}; command.command.opcode = HALO_METAL_CREATE_GEOMETRY;
        command.resource = ref; command.vertex_count = command.index_count = 3;
        const auto vertices = input(); command.vertex_bytes = (uint32_t)vertices.size();
        const size_t start = bytes.size(); bytes.resize(start + sizeof(command),0);
        command.vertices_offset = payload(vertices.data(),vertices.size());
        const uint32_t indices[] = {0,1,invalidIndex ? 3u : 2u}; command.indices_offset = payload(indices,sizeof(indices));
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); command.command.byte_size = (uint32_t)(bytes.size() - start);
        memcpy(bytes.data() + start,&command,sizeof(command)); commands++; return command.vertices_offset;
    }
    void geometryDraw(halo_metal_ref ref,uint8_t red,bool compact = false,bool mismatched = false) {
        halo_metal_draw command{}; command.command.opcode = compact ? HALO_METAL_DRAW_COMPACT : HALO_METAL_DRAW_GEOMETRY;
        command.program = {1,1}; command.color = {1,1}; command.vertex_count = mismatched ? 4 : 3; command.index_count = 3;
        command.primitive = MTLPrimitiveTypeTriangle;
        auto &s = command.state; s.color_write_mask = 15; s.blend_source = s.blend_destination = s.blend_operation = 1;
        s.depth_compare = s.stencil_compare = 8; s.stencil_fail = s.stencil_depth_fail = s.stencil_pass = 1;
        s.viewport[2] = s.viewport[3] = 4; s.viewport[5] = 1; s.scissor[2] = s.scissor[3] = 4;
        const size_t start = bytes.size(); bytes.resize(start + sizeof(halo_metal_draw_geometry),0);
        const auto vertices = input();
        if (compact) {
            command.vertices_offset = payload(vertices.data(),vertices.size());
            const uint32_t indices[] = {0,1,2}; command.indices_offset = payload(indices,sizeof(indices));
        }
        command.vertex_uniforms_offset = payload(nullptr,HaloMetalVertexUniformSize);
        command.pixel_uniforms_offset = payload(nullptr,HaloMetalPixelUniformSize);
        const float color[] = {red / 255.0f,22.0f / 255.0f,33.0f / 255.0f,1};
        memcpy(bytes.data() + command.pixel_uniforms_offset,color,sizeof(color));
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); command.command.byte_size = (uint32_t)(bytes.size() - start);
        if (compact) {
            halo_metal_draw_compact extended{command,(uint32_t)vertices.size(),0,0,0};
            memcpy(bytes.data() + start,&extended,sizeof(extended));
        } else {
            halo_metal_draw_geometry extended{command,ref,0,0}; memcpy(bytes.data() + start,&extended,sizeof(extended));
        }
        commands++;
    }
    void deleteGeometry(halo_metal_ref ref) { append(halo_metal_delete{{HALO_METAL_DELETE_GEOMETRY,0},ref}); }
};
static void run_geometry_tests() {
    host_metal_shutdown(); initialize(true);
    GeometryPacket disabled(2); disabled.createGeometry({1,1});
    require(disabled.submit() == HALO_METAL_UNSUPPORTED && context.geometry.empty() && context.submitted == 1,
        "geometry creation requires explicit opt-in");
    const auto setup = [](bool async) {
        host_metal_shutdown();
        require(host_metal_initialize(0,HALO_METAL_OFFSCREEN | HALO_METAL_ENABLE_COMPACT_VERTICES |
            HALO_METAL_ENABLE_GEOMETRY_CACHE | (async ? HALO_METAL_ENABLE_ASYNC_SUBMIT : 0),
            base,sizeof(halo_metal_reply)) == HALO_METAL_OK,"geometry device initialization");
        halo_metal_reply reply; memcpy(&reply,guest_pointer(base),sizeof(reply));
        require((reply.capabilities & HALO_METAL_CAP_GEOMETRY_CACHE) != 0,"geometry capability opt-in");
        GeometryPacket p(1); p.geometryProgram();
        p.append(halo_metal_create{{HALO_METAL_CREATE_TEXTURE,0},{1,1},HALO_METAL_RGBA8,4,4,0});
        halo_metal_clear clear{}; clear.command.opcode = HALO_METAL_CLEAR; clear.color = {1,1};
        clear.planes = HALO_METAL_COLOR; clear.width = clear.height = 4; p.append(clear);
        require(p.submit() == HALO_METAL_OK,"geometry setup packet");
    };
    setup(false);
    GeometryPacket reference(2); reference.geometryDraw({},11,true);
    require(reference.submit() == HALO_METAL_OK,"compact geometry reference"); readback(11);
    std::array<uint8_t,64> pixels{}; memcpy(pixels.data(),guest_pointer(base + 512),pixels.size());
    const auto passes = context.draw_encoder.renderPassCount;
    GeometryPacket rejected(3); rejected.createGeometry({1,1}); rejected.geometryDraw({1,1},99); rejected.createGeometry({2,1},true);
    require(rejected.submit() == HALO_METAL_INVALID && context.submitted == 2 && context.completed == 2 &&
        context.geometry.empty() && context.geometry_generations.empty() && context.draw_encoder.renderPassCount == passes,
        "late invalid geometry rejects all creations and draws atomically"); readback(11);
    GeometryPacket accepted(3); accepted.createGeometry({1,1}); accepted.geometryDraw({1,1},11);
    require(accepted.submit() == HALO_METAL_OK,"create and draw cached geometry"); readback(11);
    require(!memcmp(pixels.data(),guest_pointer(base + 512),pixels.size()),"cached and compact geometry have exact output bytes");
    GeometryPacket stale(4); stale.geometryDraw({1,2},99);
    require(stale.submit() == HALO_METAL_STALE_RESOURCE && context.submitted == 3,"unknown geometry generation rejected");
    GeometryPacket mismatch(4); mismatch.geometryDraw({1,1},99,false,true);
    require(mismatch.submit() == HALO_METAL_INVALID && context.submitted == 3,"cached draw metadata must match immutable snapshot");
    GeometryPacket changed(4); changed.geometryDraw({1,1},44);
    require(changed.submit() == HALO_METAL_OK,"cached geometry keeps per-draw uniforms"); readback(44);
    {
        GeometryPacket owned(5); const uint32_t vertices = owned.createGeometry({2,1}); owned.geometryDraw({2,1},55); owned.copy_to_guest();
        Prepared prepared; prepared.input_buffer = packet_input_buffer(owned.bytes.size());
        require(copy_guest(packetAddress,prepared.input_buffer.contents,(uint32_t)owned.bytes.size()),"copy geometry packet");
        const HaloMetalPacketView packet(prepared.input_buffer.contents,owned.bytes.size()); validate(packet,prepared);
        memset(guest_pointer(packetAddress),0,owned.bytes.size());
        memset((uint8_t *)prepared.input_buffer.contents + vertices + sizeof(halo_metal_compact_vertex_input),0,48);
        execute(packet,prepared); readback(55);
    }
    GeometryPacket later(6); later.geometryDraw({2,1},66);
    require(later.submit() == HALO_METAL_OK,"geometry remains owned after packet storage reuse"); readback(66);
    GeometryPacket replaced(7); replaced.deleteGeometry({1,1}); replaced.createGeometry({1,2}); replaced.geometryDraw({1,2},77);
    require(replaced.submit() == HALO_METAL_OK && context.geometry.at(1).generation == 2,"deleted geometry ID safely advances generation"); readback(77);
    setup(true);
    GeometryPacket old(2); old.createGeometry({1,1}); old.geometryDraw({1,1},88);
    require(old.submit() == HALO_METAL_OK,"async cached geometry draw");
    std::weak_ptr<const HaloMetalGeometry> previous = context.geometry.at(1).input;
    GeometryPacket newer(3); newer.deleteGeometry({1,1}); newer.createGeometry({1,2}); newer.geometryDraw({1,2},99);
    require(newer.submit() == HALO_METAL_OK,"delete/recreate geometry across pending command buffers");
    if (context.completed < 2) require(!previous.expired(),"pending draw owns deleted geometry");
    readback(99); require(context.pending.empty() && context.completed == 3,"readback retires geometry work");
    GeometryPacket retired(4); retired.geometryDraw({1,1},11);
    require(retired.submit() == HALO_METAL_STALE_RESOURCE && context.submitted == 3,"deleted generation cannot draw"); readback(99);
    GeometryPacket deletion(4); deletion.deleteGeometry({1,2});
    require(deletion.submit() == HALO_METAL_OK && context.geometry.empty() && !context.geometry_bytes,"geometry delete releases live accounting");
    GeometryPacket same(5); same.createGeometry({1,2});
    require(same.submit() == HALO_METAL_STALE_RESOURCE && context.submitted == 4,"deleted generation cannot be recreated");
    GeometryPacket fresh(5); fresh.createGeometry({1,3}); fresh.geometryDraw({1,3},111);
    require(fresh.submit() == HALO_METAL_OK,"next generation recreates geometry"); readback(111);
    host_metal_shutdown();
}
static void valid_draw(uint64_t sequence,uint8_t red,size_t padding = 0) {
    Packet packet(sequence); packet.draw(red,padding); require(packet.submit() == HALO_METAL_OK,"draw packet"); readback(red);
}
struct UniformPacket : Packet {
    using Packet::Packet;
    using Vertex = std::array<uint8_t,HaloMetalVertexUniformSize>;
    using Pixel = std::array<uint8_t,HaloMetalPixelUniformSize>;
    static Pixel pixel(uint8_t red) {
        Pixel result{}; const float color[] = {red / 255.0f,22.0f / 255.0f,33.0f / 255.0f,1};
        memcpy(result.data(),color,sizeof(color)); return result;
    }
    uint32_t define(uint32_t kind,const void *data) {
        halo_metal_define_uniforms c{}; c.command.opcode = HALO_METAL_DEFINE_UNIFORMS; c.kind = kind;
        c.data_size = kind == HALO_METAL_UNIFORM_VERTEX ? HaloMetalVertexUniformSize : HaloMetalPixelUniformSize;
        const size_t start = bytes.size(); bytes.resize(start + sizeof(c),0);
        c.data_offset = payload(data,c.data_size);
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); c.command.byte_size = (uint32_t)(bytes.size() - start);
        memcpy(bytes.data() + start,&c,sizeof(c)); commands++; return c.data_offset;
    }
    size_t drawRefs(uint32_t vertex,uint32_t pixel,uint32_t inputKind = HALO_METAL_INPUT_EXPANDED,
                    halo_metal_ref geometry = {}) {
        halo_metal_draw_uniform_refs c{}; c.draw.command.opcode = HALO_METAL_DRAW_UNIFORM_REFS;
        c.draw.program = {1,1}; c.draw.color = {1,1}; c.draw.vertex_count = c.draw.index_count = 3;
        c.draw.primitive = MTLPrimitiveTypeTriangle; c.input_kind = inputKind; c.geometry = geometry;
        auto &s = c.draw.state; s.color_write_mask = 15; s.blend_source = s.blend_destination = s.blend_operation = 1;
        s.depth_compare = s.stencil_compare = 8; s.stencil_fail = s.stencil_depth_fail = s.stencil_pass = 1;
        s.viewport[2] = s.viewport[3] = 4; s.viewport[5] = 1; s.scissor[2] = s.scissor[3] = 4;
        const size_t start = bytes.size(); bytes.resize(start + sizeof(c),0);
        if (inputKind != HALO_METAL_INPUT_GEOMETRY) {
            if (inputKind == HALO_METAL_INPUT_COMPACT) {
                const auto vertices = GeometryPacket::input(); c.vertex_bytes = (uint32_t)vertices.size();
                c.draw.vertices_offset = payload(vertices.data(),vertices.size());
            } else c.draw.vertices_offset = payload(nullptr,3 * HaloMetalVertexStride);
            const uint32_t indices[] = {0,1,2}; c.draw.indices_offset = payload(indices,sizeof(indices));
        }
        c.draw.vertex_uniforms_offset = vertex; c.draw.pixel_uniforms_offset = pixel;
        bytes.resize((bytes.size() + 7u) & ~size_t(7u),0); c.draw.command.byte_size = (uint32_t)(bytes.size() - start);
        memcpy(bytes.data() + start,&c,sizeof(c)); commands++; return start;
    }
    void legacy(const Vertex &vertex,const Pixel &pixel,bool right = false) {
        const size_t start = bytes.size(); draw(0);
        halo_metal_draw c; memcpy(&c,bytes.data() + start,sizeof(c));
        memcpy(bytes.data() + c.vertex_uniforms_offset,vertex.data(),vertex.size());
        memcpy(bytes.data() + c.pixel_uniforms_offset,pixel.data(),pixel.size());
        c.state.scissor[0] = right ? 2 : 0; c.state.scissor[2] = 2;
        memcpy(bytes.data() + start,&c,sizeof(c));
    }
    void half(size_t start,bool right) {
        halo_metal_draw c; memcpy(&c,bytes.data() + start,sizeof(c));
        c.state.scissor[0] = right ? 2 : 0; c.state.scissor[2] = 2;
        memcpy(bytes.data() + start,&c,sizeof(c));
    }
};
static std::array<uint8_t,64> captured_color() {
    require(host_metal_readback(1,1,HALO_METAL_COLOR,base+512,64,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "uniform fixture color readback");
    std::array<uint8_t,64> result; memcpy(result.data(),guest_pointer(base+512),result.size()); return result;
}
static uint64_t captured_query() {
    require(host_metal_readback(5,1,HALO_METAL_VISIBILITY,base+256,8,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "uniform fixture query readback");
    uint64_t result; memcpy(&result,guest_pointer(base+256),sizeof(result)); return result;
}
struct ClearPacket : Packet {
    using Packet::Packet;
    void colorDraw(const float rgba[4],uint32_t mask = 15,uint32_t x = 0,uint32_t width = 4,
                   halo_metal_ref depth = {},bool additive = false,uint32_t stencil = 7,uint32_t height = 4) {
        const size_t start = bytes.size(); draw(0);
        halo_metal_draw c; memcpy(&c,bytes.data()+start,sizeof(c));
        c.depth_stencil = depth; c.state.color_write_mask = mask;
        c.state.scissor[0] = x; c.state.scissor[2] = width; c.state.scissor[3] = height;
        c.state.blend_enabled = 1; c.state.blend_source = 2;
        c.state.blend_destination = additive ? 2 : 1;
        if (depth.id) {
            c.state.depth_enabled = c.state.depth_write = 1; c.state.depth_compare = 2;
            c.state.viewport[4] = .25f;
            c.state.stencil_enabled = 1; c.state.stencil_compare = 3;
            c.state.stencil_reference = stencil; c.state.stencil_read_mask = c.state.stencil_write_mask = 255;
            c.state.stencil_pass = 4;
        }
        memcpy(bytes.data()+c.pixel_uniforms_offset,rgba,16); memcpy(bytes.data()+start,&c,sizeof(c));
    }
    void clearing(uint32_t planes = 7,uint32_t mask = 15,uint32_t width = 4,
                  halo_metal_ref color = {1,1},halo_metal_ref depth = {2,1}) {
        halo_metal_clear c{}; c.command.opcode = mask == 15 ? HALO_METAL_CLEAR : HALO_METAL_CLEAR_CHANNELS;
        c.color = planes & HALO_METAL_COLOR ? color : halo_metal_ref{};
        c.depth_stencil = planes & 6 ? depth : halo_metal_ref{};
        c.planes = planes; c.width = c.height = width;
        c.rgba[0] = .49f/255; c.rgba[1] = .51f/255; c.rgba[2] = 10.49f/255; c.rgba[3] = 127.51f/255;
        c.depth = .75f; c.stencil = 7;
        if (mask == 15) append(c);
        else {
            halo_metal_clear_channels extended{c,mask,0}; extended.clear.command.byte_size = sizeof(extended);
            const size_t start = bytes.size(); bytes.resize(start+sizeof(extended),0);
            memcpy(bytes.data()+start,&extended,sizeof(extended)); commands++;
        }
    }
};
static std::vector<uint8_t> captured_plane(uint32_t resource,uint32_t plane,uint32_t extent = 4) {
    const uint32_t size = extent*extent*(plane == HALO_METAL_STENCIL ? 1 : 4);
    require(host_metal_readback(resource,1,plane,base+512,size,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "clear fixture plane readback");
    const auto *data = (const uint8_t *)guest_pointer(base+512);
    return {data,data+size};
}
static void initialize_clear_fixture() {
    host_metal_shutdown();
    require(host_metal_initialize(0,HALO_METAL_OFFSCREEN,base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "clear fixture device initialization");
    ClearPacket setup(1); setup.program();
    for (uint32_t id : {1u,3u})
        setup.append(halo_metal_create{{HALO_METAL_CREATE_TEXTURE,0},{id,1},HALO_METAL_BGRA8,4,4,0});
    for (uint32_t id : {2u,4u})
        setup.append(halo_metal_create{{HALO_METAL_CREATE_TEXTURE,0},{id,1},HALO_METAL_DEPTH32_STENCIL8,
            id == 2 ? 4u : 8u,id == 2 ? 4u : 8u,0});
    const auto seed = [&](uint32_t planes,uint32_t extent,halo_metal_ref color,halo_metal_ref depth) {
        const size_t position = setup.bytes.size(); setup.clearing(planes,15,extent,color,depth);
        halo_metal_clear c; memcpy(&c,setup.bytes.data()+position,sizeof(c));
        const float rgba[] = {15.49f/255,25.51f/255,35.49f/255,45.51f/255};
        memcpy(c.rgba,rgba,16); c.depth = .875f; c.stencil = 5;
        memcpy(setup.bytes.data()+position,&c,sizeof(c));
    };
    seed(7,4,{1,1},{2,1}); seed(HALO_METAL_COLOR,4,{3,1},{});
    seed(HALO_METAL_DEPTH|HALO_METAL_STENCIL,8,{}, {4,1});
    setup.append(halo_metal_create_visibility{{HALO_METAL_CREATE_VISIBILITY,0},{5,1},HALO_METAL_VISIBILITY_COUNTING,0});
    require(setup.submit() == HALO_METAL_OK,"clear fixture resource initialization");
}
static void submit_clear_plan(ClearPacket &p,bool shouldFold,uint32_t mask = 15) {
    p.copy_to_guest(); Prepared prepared;
    prepared.input_buffer = packet_input_buffer(p.bytes.size());
    require(copy_guest(packetAddress,prepared.input_buffer.contents,(uint32_t)p.bytes.size()),"owned clear fixture packet");
    const HaloMetalPacketView view(prepared.input_buffer.contents,p.bytes.size()); validate(view,prepared);
    const size_t position = sizeof(halo_metal_packet);
    const auto c = record<halo_metal_clear>(view,position);
    size_t drawPosition = 0;
    auto folded = clear_before_draw(view,prepared,0,position,c,mask,drawPosition);
    require(bool(folded) == shouldFold,"clear eligibility must retain observable boundaries and exact footprint");
    const auto passes = context.draw_encoder.renderPassCount;
    execute(view,prepared);
    if (shouldFold) require(context.draw_encoder.renderPassCount == passes+1,
        "folded full clear starts one pass shared by both masked replacement draws");
}
static void run_clear_fusion_tests() {
    const float color[] = {200.51f/255,99.49f/255,50.51f/255,31.49f/255};
    const auto snapshot = [] {
        std::vector<uint8_t> result;
        for (const auto &bytes : {captured_plane(1,HALO_METAL_COLOR),captured_plane(2,HALO_METAL_DEPTH),
                captured_plane(2,HALO_METAL_STENCIL),captured_plane(3,HALO_METAL_COLOR),
                captured_plane(4,HALO_METAL_DEPTH,8),captured_plane(4,HALO_METAL_STENCIL,8)})
            result.insert(result.end(),bytes.begin(),bytes.end());
        return result;
    };
    // A separately submitted clear is the original store/quantization reference.
    // Masked replacement draws leave fractional clear channels observable.
    for (uint32_t planes : {7u,1u,2u,4u}) {
        std::vector<uint8_t> expected;
        for (bool together : {false,true}) {
            initialize_clear_fixture(); ClearPacket p(2); p.clearing(planes);
            if (!together) { require(p.submit() == HALO_METAL_OK,"separate full clear reference"); p = ClearPacket(3); }
            const uint32_t reference = planes & HALO_METAL_STENCIL ? 7 : 5;
            p.colorDraw(color,9,0,2,{2,1},false,reference,3);
            p.colorDraw(color,6,2,2,{2,1},false,reference,3);
            if (together) submit_clear_plan(p,true);
            else require(p.submit() == HALO_METAL_OK,"draw after separate full clear");
            const auto actual = snapshot();
            if (!together) expected = actual;
            else require(actual == expected,"fused full-clear color/depth/stencil bytes match standalone store reference");
            const auto pixels = captured_plane(1,HALO_METAL_COLOR);
            const auto depths = captured_plane(2,HALO_METAL_DEPTH), stencil = captured_plane(2,HALO_METAL_STENCIL);
            for (unsigned i = 0; i < 16; i++) {
                const bool left = i%4 < 2, drawn = i/4 < 3, clearColor = planes & HALO_METAL_COLOR;
                const uint8_t bgra[] = {uint8_t(drawn && !left ? 51 : clearColor ? 10 : 35),
                    uint8_t(drawn && !left ? 99 : clearColor ? 1 : 26),
                    uint8_t(drawn && left ? 201 : clearColor ? 0 : 15),
                    uint8_t(drawn && left ? 31 : clearColor ? 128 : 46)};
                float z; memcpy(&z,depths.data()+i*4,4);
                const float expectedDepth = drawn ? .25f : planes & HALO_METAL_DEPTH ? .75f : .875f;
                require(!memcmp(pixels.data()+i*4,bgra,4) && z == expectedDepth &&
                    stencil[i] == reference + (drawn ? 1 : 0),
                    "fractional BGRA clear, logical masks, alpha and depth/stencil comparisons have analytic results");
            }
        }
    }
    // Adding two sub-half-byte values without an intervening UNorm store
    // yields 1; the original clear store rounds the destination to 0 first.
    const float fractional[] = {.49f/255,.49f/255,.49f/255,.49f/255};
    initialize_clear_fixture(); ClearPacket additive(2); additive.clearing(HALO_METAL_COLOR);
    halo_metal_clear c; memcpy(&c,additive.bytes.data()+sizeof(halo_metal_packet),sizeof(c));
    memcpy(c.rgba,fractional,16); memcpy(additive.bytes.data()+sizeof(halo_metal_packet),&c,sizeof(c));
    additive.colorDraw(fractional,15,0,4,{},true); submit_clear_plan(additive,false);
    const auto zero = captured_plane(1,HALO_METAL_COLOR);
    require(std::all_of(zero.begin(),zero.end(),[](uint8_t value) { return value == 0; }),
        "destination-dependent first draw reads separately quantized fractional clear");
    // These cases must preserve partial clears, aspect masks, query results,
    // copies observing the clear, and exact attachment/footprint ordering.
    for (unsigned kind = 0; kind < 6; kind++) {
        std::vector<uint8_t> expected;
        for (bool together : {false,true}) {
            initialize_clear_fixture(); ClearPacket p(2);
            if (kind == 0) p.clearing(HALO_METAL_COLOR,15,2);
            else if (kind == 1) p.clearing(HALO_METAL_COLOR,9);
            else if (kind == 4) p.clearing(HALO_METAL_COLOR,15,4,{3,1});
            else if (kind == 5) p.clearing(HALO_METAL_DEPTH|HALO_METAL_STENCIL,15,8,{}, {4,1});
            else p.clearing(HALO_METAL_COLOR);
            if (!together) { require(p.submit() == HALO_METAL_OK,"isolated boundary clear reference"); p = ClearPacket(3); }
            if (kind == 2) p.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{5,1}});
            if (kind == 3) p.append(halo_metal_copy{{HALO_METAL_COPY,0},{1,1},{3,1},0,0,0,0,4,4});
            p.colorDraw(color,9,0,2,kind == 5 ? halo_metal_ref{4,1} : halo_metal_ref{});
            if (kind == 2) p.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{5,1}});
            if (together) submit_clear_plan(p,false,kind == 1 ? 9 : 15);
            else require(p.submit() == HALO_METAL_OK,"isolated boundary draw reference");
            const auto actual = snapshot();
            if (!together) expected = actual;
            else require(actual == expected,"nonfusible clear preserves original observable plane bytes");
            if (kind == 2) require(captured_query() == 8,"clear boundary query counts only eight drawn samples");
        }
    }
    host_metal_shutdown();
}
static void run_uniform_tests() {
    host_metal_shutdown(); initialize();
    UniformPacket::Vertex vertex{};
    // Raw original registers may contain nonfinite unused lanes. Their bits
    // must survive sharing; the separate native controls remain finite.
    const uint32_t rawNaN = 0x7fc00001; memcpy(vertex.data(),&rawNaN,sizeof(rawNaN));
    const auto pixel = UniformPacket::pixel(44);
    auto changed = pixel; changed[2] ^= 0x40; // Exactly one changed byte in the rendered red constant.
    UniformPacket disabled(2); disabled.define(HALO_METAL_UNIFORM_VERTEX,vertex.data());
    require(disabled.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 1,"uniform definition requires opt-in");
    UniformPacket disabledDraw(2); disabledDraw.drawRefs(0,0);
    require(disabledDraw.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 1,"uniform reference draw requires opt-in");
    host_metal_shutdown(); initialize(true,false,true,true);
    GeometryPacket geometry(2); geometry.createGeometry({1,1});
    require(geometry.submit() == HALO_METAL_OK,"geometry for shared-uniform input comparison");
    UniformPacket reference(3);
    reference.append(halo_metal_create_visibility{{HALO_METAL_CREATE_VISIBILITY,0},{5,1},HALO_METAL_VISIBILITY_COUNTING,0});
    reference.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{5,1}});
    reference.legacy(vertex,pixel); reference.legacy(vertex,pixel); reference.legacy(vertex,changed,true);
    reference.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{5,1}});
    require(reference.submit() == HALO_METAL_OK,"legacy uniform byte-change reference");
    const auto expected = captured_color(); require(captured_query() == 24,"three original half-screen draws count 24 samples");
    require(expected[0] != expected[8],"single-byte constant change affects rendered reference pixels");
    uint64_t sequence = 4;
    for (uint32_t kind : {HALO_METAL_INPUT_EXPANDED,HALO_METAL_INPUT_COMPACT,HALO_METAL_INPUT_GEOMETRY}) {
        UniformPacket shared(sequence++); shared.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{5,1}});
        const auto v = shared.define(HALO_METAL_UNIFORM_VERTEX,vertex.data());
        const auto p = shared.define(HALO_METAL_UNIFORM_PIXEL,pixel.data());
        const halo_metal_ref g = kind == HALO_METAL_INPUT_GEOMETRY ? halo_metal_ref{1,1} : halo_metal_ref{};
        shared.half(shared.drawRefs(v,p,kind,g),false); shared.half(shared.drawRefs(v,p,kind,g),false);
        const auto different = shared.define(HALO_METAL_UNIFORM_PIXEL,changed.data());
        shared.half(shared.drawRefs(v,different,kind,g),true);
        shared.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{5,1}});
        const auto passes = context.draw_encoder.renderPassCount;
        require(shared.bytes.size() < reference.bytes.size() && shared.submit() == HALO_METAL_OK,
            "shared vertex/pixel definitions reduce payload for all original input kinds");
        require(captured_color() == expected && captured_query() == 24 && context.draw_encoder.renderPassCount == passes + 3,
            "repeated and single-byte-changed uniforms preserve exact color/query/pass results");
    }
    const auto reject = [&](UniformPacket &packet,const char *message,int status = HALO_METAL_INVALID) {
        const auto submitted = context.submitted, completed = context.completed;
        const auto passes = context.draw_encoder.renderPassCount;
        const auto version = context.textures.at(1).version, queryVersion = context.queries.at(5).version;
        require(packet.submit() == status && context.submitted == submitted && context.completed == completed &&
            context.draw_encoder.renderPassCount == passes && context.textures.at(1).version == version &&
            context.queries.at(5).version == queryVersion && captured_color() == expected,message);
    };
    const auto validPrefix = [&](UniformPacket &packet) {
        const auto v = packet.define(HALO_METAL_UNIFORM_VERTEX,vertex.data());
        const auto p = packet.define(HALO_METAL_UNIFORM_PIXEL,pixel.data());
        return std::pair<uint32_t,uint32_t>{v,p};
    };
    UniformPacket typed(sequence); auto refs = validPrefix(typed); typed.drawRefs(refs.second,refs.first);
    reject(typed,"uniform references cannot swap vertex and pixel kinds");
    UniformPacket interior(sequence); refs = validPrefix(interior); interior.drawRefs(refs.first+16,refs.second);
    reject(interior,"uniform references reject aligned interior payload slices");
    UniformPacket padding(sequence); refs = validPrefix(padding); padding.drawRefs(refs.first-16,refs.second);
    reject(padding,"uniform references reject definition header/padding bytes");
    UniformPacket future(sequence); const auto futureDraw = future.drawRefs(0,0); refs = validPrefix(future);
    halo_metal_draw draw; memcpy(&draw,future.bytes.data()+futureDraw,sizeof(draw));
    draw.vertex_uniforms_offset = refs.first; draw.pixel_uniforms_offset = refs.second;
    memcpy(future.bytes.data()+futureDraw,&draw,sizeof(draw));
    reject(future,"uniform references cannot point to future definitions");
    UniformPacket previous(sequence); previous.drawRefs(refs.first,refs.second);
    reject(previous,"uniform definitions do not leak across packets");
    UniformPacket arbitrary(sequence); const auto legacyStart = arbitrary.bytes.size(); arbitrary.legacy(vertex,pixel);
    memcpy(&draw,arbitrary.bytes.data()+legacyStart,sizeof(draw)); arbitrary.drawRefs(draw.vertex_uniforms_offset,draw.pixel_uniforms_offset);
    reject(arbitrary,"earlier legacy payloads are not typed uniform definitions");
    UniformPacket legacyRange(sequence); refs = validPrefix(legacyRange); const auto legacyDraw = legacyRange.bytes.size();
    legacyRange.legacy(vertex,pixel); memcpy(&draw,legacyRange.bytes.data()+legacyDraw,sizeof(draw));
    draw.vertex_uniforms_offset = refs.first; draw.pixel_uniforms_offset = refs.second;
    memcpy(legacyRange.bytes.data()+legacyDraw,&draw,sizeof(draw));
    reject(legacyRange,"legacy uniform bounds remain command-local even with sharing enabled");
    UniformPacket lateNaN(sequence); refs = validPrefix(lateNaN); lateNaN.drawRefs(refs.first,refs.second);
    auto invalidPixel = pixel; memcpy(invalidPixel.data()+4,&rawNaN,sizeof(rawNaN)); lateNaN.define(HALO_METAL_UNIFORM_PIXEL,invalidPixel.data());
    reject(lateNaN,"late nonfinite pixel definition rejects earlier valid draws atomically");
    UniformPacket lateVertexNaN(sequence); refs = validPrefix(lateVertexNaN); lateVertexNaN.drawRefs(refs.first,refs.second);
    auto invalidVertex = vertex; memcpy(invalidVertex.data()+3072,&rawNaN,sizeof(rawNaN));
    lateVertexNaN.define(HALO_METAL_UNIFORM_VERTEX,invalidVertex.data());
    reject(lateVertexNaN,"nonfinite native vertex controls reject the whole packet");
    UniformPacket wrongSize(sequence); wrongSize.define(HALO_METAL_UNIFORM_VERTEX,vertex.data());
    halo_metal_define_uniforms definition; memcpy(&definition,wrongSize.bytes.data()+sizeof(halo_metal_packet),sizeof(definition));
    definition.data_size--; memcpy(wrongSize.bytes.data()+sizeof(halo_metal_packet),&definition,sizeof(definition));
    reject(wrongSize,"uniform definitions require the complete typed block size");
    UniformPacket stale(sequence); refs = validPrefix(stale); stale.drawRefs(refs.first,refs.second,HALO_METAL_INPUT_GEOMETRY,{1,2});
    reject(stale,"shared-uniform cached draw requires current geometry generation",HALO_METAL_STALE_RESOURCE);
    UniformPacket mismatch(sequence); refs = validPrefix(mismatch); const auto mismatched = mismatch.drawRefs(refs.first,refs.second,HALO_METAL_INPUT_GEOMETRY,{1,1});
    memcpy(&draw,mismatch.bytes.data()+mismatched,sizeof(draw)); draw.vertex_count = 4;
    memcpy(mismatch.bytes.data()+mismatched,&draw,sizeof(draw)); reject(mismatch,"shared-uniform cached draw keeps exact geometry metadata");
    // Definitions between compatible draws must not create GPU pass boundaries.
    UniformPacket opaque(sequence++); refs = validPrefix(opaque); opaque.drawRefs(refs.first,refs.second);
    const auto newPixel = opaque.define(HALO_METAL_UNIFORM_PIXEL,pixel.data()); opaque.drawRefs(refs.first,newPixel);
    const auto passes = context.draw_encoder.renderPassCount;
    require(opaque.submit() == HALO_METAL_OK && context.draw_encoder.renderPassCount == passes+1,
        "uniform metadata does not interrupt a compatible original draw pass"); readback(44);
    host_metal_shutdown(); initialize(false,true,true); captured_color();
    auto event = [context.device newSharedEvent]; auto gate = [context.queue commandBuffer];
    [gate encodeWaitForEvent:event value:1]; [gate commit];
    UniformPacket owned(2); const auto ownedVertex = owned.define(HALO_METAL_UNIFORM_VERTEX,vertex.data());
    const auto ownedPixelData = UniformPacket::pixel(88);
    const auto ownedPixel = owned.define(HALO_METAL_UNIFORM_PIXEL,ownedPixelData.data()); owned.drawRefs(ownedVertex,ownedPixel);
    require(owned.submit() == HALO_METAL_OK && context.completed == 1 && context.pending.size() == 1,"shared uniform async packet accepted behind gate");
    const auto &prepared = context.pending.front().prepared;
    const HaloMetalDraw &preparedDraw = [prepared.draws.begin()->second draw];
    require(preparedDraw.vertexUniforms == prepared.input_buffer && preparedDraw.pixelUniforms == prepared.input_buffer &&
        preparedDraw.vertexUniformOffset == ownedVertex && preparedDraw.pixelUniformOffset == ownedPixel,
        "shared uniforms reference the same GPU-owned packet snapshot");
    memset(guest_pointer(packetAddress),0,owned.bytes.size());
    require(!memcmp((const uint8_t *)prepared.input_buffer.contents+ownedPixel,ownedPixelData.data(),ownedPixelData.size()),
        "guest reuse cannot overwrite pending shared uniform bytes");
    event.signaledValue = 1; readback(88);
    require(context.pending.empty() && context.completed == 2,"readback retires shared uniform ownership");
    UniformPacket crossPacket(3); crossPacket.drawRefs(ownedVertex,ownedPixel);
    require(crossPacket.submit() == HALO_METAL_INVALID && context.submitted == 2,"retired packet definitions cannot be referenced"); readback(88);
    host_metal_shutdown();
}
static void append_fence(Packet &packet) {
    const halo_metal_command command{HALO_METAL_FENCE,sizeof(halo_metal_command)};
    const size_t start = packet.bytes.size(); packet.bytes.resize(start + sizeof(command),0);
    memcpy(packet.bytes.data() + start,&command,sizeof(command)); packet.commands++;
}
static void run_async_query_prefix_tests() {
    host_metal_shutdown(); initialize(true,true); valid_draw(2,155);
    auto prefixEvent = [context.device newSharedEvent]; auto tailEvent = [context.device newSharedEvent];
    require(prefixEvent && tailEvent,"query prefix shared events");
    auto prefixGate = [context.queue commandBuffer];
    [prefixGate encodeWaitForEvent:prefixEvent value:1]; [prefixGate commit];
    Packet prefix(3);
    prefix.append(halo_metal_create_visibility{{HALO_METAL_CREATE_VISIBILITY,0},{2,1},HALO_METAL_VISIBILITY_BOOLEAN,0});
    prefix.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{2,1}}); prefix.draw(166);
    prefix.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{2,1}});
    require(prefix.submit() == HALO_METAL_OK && context.pending.size() == 1 && context.completed == 2,
        "query prefix is accepted while incomplete");
    auto prefixCommand = context.pending.front().command;
    auto tailGate = [context.queue commandBuffer];
    [tailGate encodeWaitForEvent:tailEvent value:1]; [tailGate commit];
    Packet tail(4); tail.draw(177);
    require(tail.submit() == HALO_METAL_OK && context.pending.size() == 2,"later drawing is accepted after query prefix");
    auto tailBuffer = context.pending.back().prepared.input_buffer;
    memset(guest_pointer(packetAddress),0,tail.bytes.size());
    prefixEvent.signaledValue = 1; [prefixCommand waitUntilCompleted];
    require(prefixCommand.status == MTLCommandBufferStatusCompleted && context.completed == 2,
        "completed query prefix still requires honest host retirement");
    std::atomic<bool> readReturned{false}, returnedBeforeTailRelease{false};
    std::thread release([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        returnedBeforeTailRelease = readReturned.load(); tailEvent.signaledValue = 1;
    });
    uint64_t result = 0;
    const int status = host_metal_readback(2,1,HALO_METAL_VISIBILITY,base+256,sizeof(result),base,sizeof(halo_metal_reply));
    readReturned = true;
    memcpy(&result,guest_pointer(base+256),sizeof(result));
    halo_metal_reply reply; memcpy(&reply,guest_pointer(base),sizeof(reply));
    const bool pendingTail = context.pending.size() == 1 && context.pending.front().sequence == 4 &&
        context.pending.front().command.status != MTLCommandBufferStatusCompleted && context.completed == 3 &&
        context.pending.front().prepared.input_buffer == tailBuffer &&
        !memcmp(tailBuffer.contents,tail.bytes.data(),tail.bytes.size());
    release.join();
    require(returnedBeforeTailRelease && status == HALO_METAL_OK && result == 1 && pendingTail,
        "visibility readback waits only through END and preserves later gated packet ownership");
    require(reply.submitted_sequence == 4 && reply.completed_sequence == 3 && reply.content_version == 1 &&
        reply.byte_size == sizeof(result),"query result and completed sequence are exact while later work remains pending");
    readback(177);
    require(context.pending.empty() && context.completed == 4,"color readback retains its full completion boundary");
}
static void run_async_frame_budget_tests() {
    host_metal_shutdown(); initialize(true,true); valid_draw(2,155);
    auto event = [context.device newSharedEvent]; auto gate = [context.queue commandBuffer];
    require(event && gate,"frame budget queue gate");
    [gate encodeWaitForEvent:event value:1]; [gate commit];
    Packet first(3); first.draw(166); require(first.submit() == HALO_METAL_OK,"first frame-budget packet");
    Packet second(4); second.draw(177); require(second.submit() == HALO_METAL_OK,"second frame-budget packet");
    // This fixture has no window/layer. Mark the accepted real GPU packets as
    // frame ends to exercise admission, not onscreen presentation behavior.
    context.pending[0].presented = true; context.pending[1].presented = true;
    std::atomic<bool> returned{false}, returnedBeforeRelease{false};
    std::thread release([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        returnedBeforeRelease = returned.load(); event.signaledValue = 1;
    });
    Packet prefix(5); prefix.draw(188); const int status = prefix.submit(); returned = true;
    release.join();
    require(!returnedBeforeRelease && status == HALO_METAL_OK,
        "two queued presentations block the next prefix despite spare packet slots");
    readback(188);
    require(context.pending.empty() && context.completed == 5,"frame budget wait preserves ordered GPU completion");
}
static void run_async_tests() {
    // A real queue wait makes ownership deterministic: GPU work cannot consume
    // either snapshot until the CPU explicitly releases this shared event.
    host_metal_shutdown(); initialize(true,true); valid_draw(2,155);
    auto event = [context.device newSharedEvent]; require(event != nil,"async shared event");
    auto gate = [context.queue commandBuffer]; require(gate != nil,"async queue gate");
    [gate encodeWaitForEvent:event value:1]; [gate commit];
    Packet first(3); first.draw(166); require(first.submit() == HALO_METAL_OK,"first owned async draw");
    require(context.pending.size() == 1 && context.completed == 2,"submit acknowledges incomplete work honestly");
    auto firstBuffer = context.pending.front().prepared.input_buffer;
    memset(guest_pointer(packetAddress),0,first.bytes.size());
    const auto version = context.textures.at(1).version;
    const auto passes = context.draw_encoder.renderPassCount;
    Packet rejected(4); rejected.draw(199); rejected.invalid();
    require(rejected.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 3 && context.completed == 2 &&
        context.pending.size() == 1 && context.textures.at(1).version == version &&
        context.draw_encoder.renderPassCount == passes,"late rejection leaves accepted queued work and content unchanged");
    Packet second(4); second.draw(177); require(second.submit() == HALO_METAL_OK,"second owned async draw");
    require(context.pending.size() == 2 && firstBuffer != context.pending.back().prepared.input_buffer,
        "two pending packets use distinct owned buffers");
    memset(guest_pointer(packetAddress),0,second.bytes.size());
    require(!memcmp(firstBuffer.contents,first.bytes.data(),first.bytes.size()) &&
        !memcmp(context.pending.back().prepared.input_buffer.contents,second.bytes.data(),second.bytes.size()),
        "guest mutation and later packet copy preserve both pending snapshots");
    Packet third(5); third.draw(188); require(third.submit() == HALO_METAL_OK,"third owned split-frame packet");
    Packet fourth(6); fourth.draw(189); require(fourth.submit() == HALO_METAL_OK,"fourth owned split-frame packet");
    require(context.pending.size() == 4,"two split frames can retain four packets without waiting");
    const Packet *snapshots[] = {&first,&second,&third,&fourth};
    for (size_t i = 0; i < 4; ++i) {
        const auto buffer = context.pending[i].prepared.input_buffer;
        require(!memcmp(buffer.contents,snapshots[i]->bytes.data(),snapshots[i]->bytes.size()),
            "all queued packets retain original bytes after guest reuse");
        for (size_t j = 0; j < i; ++j)
            require(buffer != context.pending[j].prepared.input_buffer,"each queued packet owns distinct storage");
    }
    std::atomic<bool> fifthReturned{false}, returnedBeforeRelease{false};
    std::thread release([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        returnedBeforeRelease = fifthReturned.load(); event.signaledValue = 1;
    });
    Packet fifth(7); fifth.draw(190); const int fifthStatus = fifth.submit(); fifthReturned = true;
    release.join();
    require(!returnedBeforeRelease && fifthStatus == HALO_METAL_OK && context.pending.size() <= 4,
        "fifth packet waits for owned slot instead of increasing queue depth");
    readback(190);
    require(context.pending.empty() && context.completed == 7,"readback drains ordered submissions");
    for (const auto &slot : context.async_input_buffers)
        require(slot.length <= 16u*1024u*1024u,"all four async buffers retain bounded capacity");
    Packet draw(8); draw.draw(199); require(draw.submit() == HALO_METAL_OK,"draw before explicit fence");
    Packet fence(9); append_fence(fence); require(fence.submit() == HALO_METAL_OK &&
        context.completed == 9 && context.pending.empty(),"explicit fence completes all earlier packets"); readback(199);
    Packet oversized(10); oversized.draw(201,17u*1024u*1024u);
    require(oversized.submit() == HALO_METAL_OK,"oversized async packet");
    memset(guest_pointer(packetAddress),0,oversized.bytes.size());
    Packet following(11); following.draw(202); require(following.submit() == HALO_METAL_OK,"packet after oversized submission");
    readback(202);
    for (const auto &slot : context.async_input_buffers)
        require(slot.length <= 16u*1024u*1024u,"oversized async input never enlarges retained pool");
    Packet begin(12);
    begin.append(halo_metal_create_visibility{{HALO_METAL_CREATE_VISIBILITY,0},{2,1},HALO_METAL_VISIBILITY_BOOLEAN,0});
    begin.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{2,1}}); begin.draw(203);
    require(begin.submit() == HALO_METAL_OK,"query begin and draw in async packet");
    Packet end(13); end.draw(204); end.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{2,1}});
    require(end.submit() == HALO_METAL_OK,"query draws and END across async packets");
    uint64_t result = 0;
    require(host_metal_readback(2,1,HALO_METAL_VISIBILITY,base+256,sizeof(result),base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "visibility readback fences END sequence"); memcpy(&result,guest_pointer(base+256),sizeof(result));
    require(result == 1 && context.completed == 13 && context.pending.empty(),"queued Boolean query has actual visible samples");
    Packet again(14); again.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{2,1}}); again.draw(205);
    again.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{2,1}});
    require(again.submit() == HALO_METAL_OK,"second query with pending result words");
    Packet reset(15); reset.append(halo_metal_visibility{{HALO_METAL_BEGIN_VISIBILITY,0},{2,1}});
    reset.append(halo_metal_visibility{{HALO_METAL_END_VISIBILITY,0},{2,1}});
    require(reset.submit() == HALO_METAL_OK,"empty query resets pending old result words");
    require(host_metal_readback(2,1,HALO_METAL_VISIBILITY,base+256,sizeof(result),base,sizeof(halo_metal_reply)) == HALO_METAL_OK,
        "reset visibility readback"); memcpy(&result,guest_pointer(base+256),sizeof(result));
    require(!result && context.completed == 15,"earlier GPU query writes cannot contaminate reset result");
    auto shutdownEvent = [context.device newSharedEvent]; auto shutdownGate = [context.queue commandBuffer];
    [shutdownGate encodeWaitForEvent:shutdownEvent value:1]; [shutdownGate commit];
    Packet final(16); final.draw(206); require(final.submit() == HALO_METAL_OK && !context.pending.empty(),"pending work before shutdown");
    context.poisoned = true; // Teardown must drain accepted work even after poison.
    std::thread shutdownRelease([&] { std::this_thread::sleep_for(std::chrono::milliseconds(20)); shutdownEvent.signaledValue = 1; });
    host_metal_shutdown(); shutdownRelease.join();
    require(shutdownGate.status == MTLCommandBufferStatusCompleted && !context.device && context.pending.empty(),
        "poisoned shutdown drains accepted GPU work before clearing ownership");
    initialize(); valid_draw(2,207);
    Packet disabled(3); append_fence(disabled);
    require(disabled.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 2 && context.completed == 2,
        "legacy context does not silently accept async fence opcode");
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
            // The original guest may reuse transient packet bytes after the
            // host copy. Validation and encoding must retain the one owned
            // copy, independently of guest mutations and allocation slack.
            {
                Packet captured(13); captured.draw(155); captured.copy_to_guest();
                Prepared captured_prepared;
                captured_prepared.input_buffer = packet_input_buffer(captured.bytes.size());
                require(copy_guest(packetAddress,captured_prepared.input_buffer.contents,(uint32_t)captured.bytes.size()),
                    "copy original packet into owned storage");
                const HaloMetalPacketView captured_view(captured_prepared.input_buffer.contents,captured.bytes.size());
                validate(captured_view,captured_prepared);
                memset(guest_pointer(packetAddress),0,captured.bytes.size());
                require(captured_view.data() == captured_prepared.input_buffer.contents &&
                    [captured_prepared.draws.begin()->second draw].vertices == captured_prepared.input_buffer &&
                    !memcmp(captured_view.data(),captured.bytes.data(),captured.bytes.size()),
                    "preflight and draw share immutable host-owned packet bytes");
                const auto token = captured_prepared.draws.begin()->second;
                HaloMetalDraw mutableDraw = [token draw];
                mutableDraw.state.color_write_mask = 16;
                NSError *error = nil;
                uint32_t used = 0;
                auto rejectedCommand = [context.queue commandBuffer];
                const auto priorPasses = context.draw_encoder.renderPassCount;
                require(![context.draw_encoder prepareDraw:mutableDraw error:&error] && error &&
                    ![context.draw_encoder usedTextureMaskForDraw:mutableDraw mask:&used error:&error] && error &&
                    ![context.draw_encoder encodeDraw:mutableDraw commandBuffer:rejectedCommand reusePass:YES error:&error] && error &&
                    [token draw].state.color_write_mask == 15 && context.draw_encoder.renderPassCount == priorPasses,
                    "retained packet preparation never grants validation bypass to a changed public draw");
                auto initial = [MTLRenderPassDescriptor renderPassDescriptor];
                initial.renderTargetWidth = 3; initial.renderTargetHeight = 4;
                initial.renderTargetArrayLength = initial.defaultRasterSampleCount = 1;
                initial.colorAttachments[0].texture = [token draw].color;
                initial.colorAttachments[0].loadAction = MTLLoadActionClear;
                initial.colorAttachments[0].storeAction = MTLStoreActionStore;
                require(![context.draw_encoder encodePreparedPacketDraw:token commandBuffer:rejectedCommand
                    reusePass:YES initialPass:initial error:&error] && error,
                    "prepared clear cannot shrink the complete target footprint");
                initial.renderTargetWidth = 4; initial.colorAttachments[1].texture = [token draw].color;
                require(![context.draw_encoder encodePreparedPacketDraw:token commandBuffer:rejectedCommand
                    reusePass:YES initialPass:initial error:&error] && error &&
                    context.draw_encoder.renderPassCount == priorPasses,
                    "prepared clear cannot inject another color attachment or encode rejected commands");
                auto otherEncoder = [[HaloMetalDrawEncoder alloc] initWithDevice:context.device];
                require(![otherEncoder encodePreparedPacketDraw:token commandBuffer:rejectedCommand
                    reusePass:YES initialPass:nil error:&error] && error,
                    "retained packet draw belongs only to its preparing encoder");
                [context.draw_encoder clearCaches];
                execute(captured_view,captured_prepared); readback(155);
            }
            Packet disabledCompact(14);disabledCompact.draw(166,0,false,true);
            require(disabledCompact.submit() == HALO_METAL_UNSUPPORTED && context.submitted == 13,
                "compact draw requires explicit opt-in");readback(155);
            host_metal_shutdown(); initialize(true); valid_draw(2,155);
            require(context.metrics.packet_buffers == 1,"shutdown releases prior storage");
            const auto passes = context.draw_encoder.renderPassCount;
            Packet invalidCompact(3);invalidCompact.draw(177);invalidCompact.draw(188,0,false,true,true);
            require(invalidCompact.submit() == HALO_METAL_INVALID && context.submitted == 2 && context.completed == 2 &&
                context.draw_encoder.renderPassCount == passes,"malformed late compact draw rejects the whole packet before GPU commands");
            readback(155);
            Packet validCompact(3);validCompact.draw(166,0,false,true);
            require(validCompact.submit() == HALO_METAL_OK,"compact packet dispatch");readback(166);
            run_geometry_tests();
            run_clear_fusion_tests();
            run_uniform_tests();
            run_async_query_prefix_tests();
            run_async_frame_budget_tests();
            run_async_tests();
            printf("{\"complete\":true,\"changing_payload_bytes\":true,\"atomic_rejection\":true,\"bounded_reuse\":true,\"retained_16mib\":true,\"exact_capacity\":true,\"growth_and_oversize\":true,\"command_ranges\":true,\"same_owned_storage\":true,\"guest_mutation_isolated\":true,\"shutdown_reset\":true,\"compact_opt_in\":true,\"compact_atomic_rejection\":true,\"geometry_wire\":true,\"geometry_owned\":true,\"geometry_generation\":true,\"uniform_sharing\":true,\"uniform_byte_equivalence\":true,\"uniform_typed_ranges\":true,\"uniform_atomic_rejection\":true,\"uniform_async_ownership\":true,\"async_snapshots\":true,\"async_bound\":true,\"async_readback_fence\":true,\"async_query_fence\":true,\"async_query_prefix\":true,\"async_poisoned_shutdown\":true}\n");
        }
        host_metal_shutdown(); return 0;
    } catch (const std::exception &error) { fprintf(stderr,"%s\n",error.what()); return 1; }
} }
