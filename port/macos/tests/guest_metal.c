/* Executes through the real rebased ILP32 import stubs, not a host mock. */
#include "../include/halo_metal_abi.h"
_Static_assert(sizeof(void *) == 4, "guest pointer layout");
static unsigned char packet[4096], color[13 * 7 * 4], stencil[13 * 7];
static float depth[13 * 7];
static struct halo_metal_reply response;
static uint32_t position, commands;

void *memcpy(void *destination,const void *source,unsigned long count) {
    unsigned char *d = destination; const unsigned char *s = source;
    for (unsigned long i = 0; i < count; i++) d[i] = s[i]; return destination;
}
void *memset(void *destination,int value,unsigned long count) {
    unsigned char *d = destination; for (unsigned long i = 0; i < count; i++) d[i] = value; return destination;
}
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static void start(uint64_t sequence) {
    position = sizeof(struct halo_metal_packet); commands = 0;
    struct halo_metal_packet h = {HALO_METAL_MAGIC,HALO_METAL_ABI_VERSION,0,0,sequence};
    memcpy(packet,&h,sizeof(h));
}
static void append(const void *c,uint32_t size) {
    memcpy(packet+position,c,size); position += size; commands++;
}
static int submit(void) {
    struct halo_metal_packet *h = (void *)packet; h->byte_size = position; h->command_count = commands;
    return host_metal_submit(address(packet),position,address(&response),sizeof(response));
}
static void create(uint32_t id,uint32_t generation,uint32_t format) {
    struct halo_metal_create c = {{HALO_METAL_CREATE_TEXTURE,sizeof(c)},{id,generation},format,13,7,0}; append(&c,sizeof(c));
}
static void upload(uint32_t generation,uint8_t red) {
    uint32_t begin = position;
    struct halo_metal_upload c = {{HALO_METAL_UPLOAD,488},{1,generation},0,0,13,7,64,begin+48,436,0};
    append(&c,sizeof(c));
    for (uint32_t y = 0; y < 7; y++) for (uint32_t x = 0; x < 13; x++) {
        unsigned char *p = packet+begin+48+y*64+x*4;
        p[0]=red+x; p[1]=21+y; p[2]=99; p[3]=255;
    }
    position = begin+488;
}
static void copy(void) {
    struct halo_metal_copy c = {{HALO_METAL_COPY,sizeof(c)},{1,1},{2,1},0,0,0,0,13,7}; append(&c,sizeof(c));
}
static void clear(int whole,uint32_t planes) {
    struct halo_metal_clear c = {{HALO_METAL_CLEAR,sizeof(c)},
        {(planes & HALO_METAL_COLOR) ? 2u : 0u,(planes & HALO_METAL_COLOR) ? 1u : 0u},
        {(planes & 6) ? 3u : 0u,(planes & 6) ? 1u : 0u},planes,
        whole ? 0u : 3u,whole ? 0u : 2u,whole ? 13u : 4u,whole ? 7u : 3u,
        whole ? 17u : 165u,{31.0f/255,67.0f/255,101.0f/255,1},whole ? .75f : .375f,0};
    append(&c,sizeof(c));
}
static int read(uint32_t id,uint32_t generation,uint32_t plane,void *target,uint32_t size) {
    return host_metal_readback(id,generation,plane,address(target),size,address(&response),sizeof(response));
}
static int check_color(uint8_t red,int box) {
    for (uint32_t y = 0; y < 7; y++) for (uint32_t x = 0; x < 13; x++) {
        int in = box && x>=3 && x<7 && y>=2 && y<5;
        const unsigned char *p = color+(y*13+x)*4;
        if (p[0] != (in ? 31 : red+x) || p[1] != (in ? 67 : 21+y) || p[2] != (in ? 101 : 99) || p[3] != 255) return 0;
    } return 1;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;
    if (host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&response),sizeof(response))) return 101;
    if (response.abi_version != 1 || (response.capabilities & 95) != 95) return 102;
    start(1); create(1,1,HALO_METAL_RGBA8); create(2,1,HALO_METAL_RGBA8); create(3,1,HALO_METAL_DEPTH32_STENCIL8);
    upload(1,17); clear(1,HALO_METAL_DEPTH|HALO_METAL_STENCIL); copy(); clear(0,7);
    if (submit() || response.completed_sequence != 1 || response.live_resources != 3) return 103;
    if (read(1,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(17,0)) return 104;
    if (read(2,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(17,1) || response.content_version != 2) return 105;
    if (read(3,1,HALO_METAL_DEPTH,depth,sizeof(depth))) return 106;
    if (read(3,1,HALO_METAL_STENCIL,stencil,sizeof(stencil))) return 107;
    for (uint32_t y = 0; y < 7; y++) for (uint32_t x = 0; x < 13; x++) {
        int in = x>=3 && x<7 && y>=2 && y<5; uint32_t i = y*13+x;
        if (depth[i] != (in ? .375f : .75f) || stencil[i] != (in ? 165 : 17)) return 108;
    }
    /* An unknown later operation rejects the whole packet before the valid
       earlier clear can alter a target or consume the frame sequence. */
    start(2); clear(1,HALO_METAL_COLOR);
    struct halo_metal_command invalid = {99,sizeof(invalid)}; append(&invalid,sizeof(invalid));
    if (submit() != HALO_METAL_UNSUPPORTED || response.failed_command != 1 || response.completed_sequence != 1) return 109;
    if (read(2,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(17,1) || response.content_version != 2) return 110;
    /* Two uploads to one target with a copy between them prove that queued
       operations use their own content versions, not the final CPU bytes. */
    start(2); upload(1,41); copy(); upload(1,73);
    if (submit()) return 111;
    memset(packet,0,sizeof(packet));
    if (read(1,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(73,0)) return 112;
    if (read(2,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(41,0)) return 113;
    start(3); struct halo_metal_delete d = {{HALO_METAL_DELETE_TEXTURE,sizeof(d)},{1,1}};
    append(&d,sizeof(d)); create(1,1,HALO_METAL_RGBA8);
    if (submit() != HALO_METAL_STALE_RESOURCE || response.failed_command != 1 || response.live_resources != 3) return 114;
    if (read(1,1,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(73,0)) return 129;
    start(3); append(&d,sizeof(d)); create(1,2,HALO_METAL_RGBA8); upload(2,97);
    if (submit()) return 115;
    if (read(1,1,HALO_METAL_COLOR,color,sizeof(color)) != HALO_METAL_STALE_RESOURCE) return 116;
    if (read(1,2,HALO_METAL_COLOR,color,sizeof(color)) || !check_color(97,0)) return 117;
    start(4); create(4,1,HALO_METAL_RGBA8); if (submit()) return 118;
    if (read(4,1,HALO_METAL_COLOR,color,sizeof(color)) != HALO_METAL_UNDEFINED_CONTENT) return 119;
    /* Stencil-only and depth-only rectangle clears preserve the other aspect. */
    start(5); clear(0,HALO_METAL_STENCIL);
    struct halo_metal_clear *last = (void *)(packet+position-sizeof(struct halo_metal_clear));
    last->depth=.125f; last->stencil=222;
    if (submit()) return 120;
    if (read(3,1,HALO_METAL_DEPTH,depth,sizeof(depth))) return 121;
    for (uint32_t y=0;y<7;y++) for (uint32_t x=0;x<13;x++)
        if (depth[y*13+x] != ((x>=3&&x<7&&y>=2&&y<5) ? .375f : .75f)) return 122;
    start(6); clear(0,HALO_METAL_DEPTH);
    last = (void *)(packet+position-sizeof(struct halo_metal_clear)); last->stencil=88; last->depth=.5f;
    if (submit()) return 123;
    if (read(3,1,HALO_METAL_STENCIL,stencil,sizeof(stencil))) return 124;
    for (uint32_t y=0;y<7;y++) for (uint32_t x=0;x<13;x++)
        if (stencil[y*13+x] != ((x>=3&&x<7&&y>=2&&y<5) ? 222 : 17)) return 125;
    if (read(3,1,HALO_METAL_DEPTH,depth,sizeof(depth))) return 130;
    for (uint32_t y=0;y<7;y++) for (uint32_t x=0;x<13;x++)
        if (depth[y*13+x] != ((x>=3&&x<7&&y>=2&&y<5) ? .5f : .75f)) return 131;
    /* Bounds and inaccessible guest pages return errors, never dereference. */
    if (host_metal_submit(0xfffffff0u,48,address(&response),sizeof(response)) != HALO_METAL_MEMORY) return 126;
    if (host_metal_submit(0x1000u,48,address(&response),sizeof(response)) != HALO_METAL_MEMORY) return 127;
    start(7); create(5,1,HALO_METAL_BGRA8); create(6,1,HALO_METAL_BGRA8); clear(1,HALO_METAL_COLOR);
    last = (void *)(packet+position-sizeof(struct halo_metal_clear)); last->color.id=5;
    struct halo_metal_copy bgra = {{HALO_METAL_COPY,sizeof(bgra)},{5,1},{6,1},0,0,0,0,13,7}; append(&bgra,sizeof(bgra));
    clear(0,HALO_METAL_COLOR); last = (void *)(packet+position-sizeof(struct halo_metal_clear));
    last->color.id=6; last->rgba[0]=17.0f/255; last->rgba[1]=19.0f/255; last->rgba[2]=23.0f/255;
    if (submit()) return 132;
    if (read(6,1,HALO_METAL_COLOR,color,sizeof(color))) return 133;
    for (uint32_t y=0;y<7;y++) for (uint32_t x=0;x<13;x++) {
        int in=x>=3&&x<7&&y>=2&&y<5; unsigned char *p=color+(y*13+x)*4;
        if (p[0]!=(in?23:101) || p[1]!=(in?19:67) || p[2]!=(in?17:31) || p[3]!=255) return 134;
    }
    host_metal_shutdown();
    if (read(1,2,HALO_METAL_COLOR,color,sizeof(color)) != HALO_METAL_NOT_INITIALIZED) return 128;
    return 0;
}
