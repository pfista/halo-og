/* Actual ILP32 C builder -> production native host imports. No game data. */
#include "../../linux/src/metal_guest_transport.h"
_Static_assert(sizeof(void *) == 4, "actual guest transport fixture");
static unsigned char storage[4096] __attribute__((aligned(16)));
static unsigned char upload[436], color[13*7*4], stencil[13*7];
static float depth[13*7];
static struct halo_metal_guest_transport transport;
uint32_t halo_transport_report[16];
int halo_transport_reply_guards(void);
int halo_transport_alpha_border_guards(void);

void *memcpy(void *destination,const void *source,unsigned long count) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(unsigned long i=0;i<count;i++)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,unsigned long count) {
    unsigned char *d=destination;for(unsigned long i=0;i<count;i++)d[i]=(unsigned char)value;return destination;
}
static int failed(uint32_t code) {
    halo_transport_report[0]=code;halo_transport_report[2]=(uint32_t)transport.status;
    halo_transport_report[3]=transport.reply.failed_command;
    halo_transport_report[4]=(uint32_t)transport.reply.submitted_sequence;
    halo_transport_report[5]=(uint32_t)(transport.reply.submitted_sequence>>32);
    halo_metal_guest_shutdown(&transport);return (int)code;
}
static int append(const void *command,uint32_t size) {
    uint32_t offset;return halo_metal_guest_append_command(&transport,command,size,&offset);
}
static int create(uint32_t id,uint32_t format) {
    struct halo_metal_create_ex c={{HALO_METAL_CREATE_TEXTURE_EX,0},{id,1},format,13,7,1,
        HALO_METAL_TEXTURE_2D,1,HALO_METAL_SHADER_READ|HALO_METAL_RENDER_TARGET,0};
    return append(&c,sizeof(c));
}
static int clear(uint32_t id,int rectangle) {
    struct halo_metal_clear c={{HALO_METAL_CLEAR,0},{id,1},{2,1},7,
        rectangle?3u:0u,rectangle?2u:0u,rectangle?4u:13u,rectangle?3u:7u,
        rectangle?9u:17u,{rectangle?0.f:.25f,rectangle?1.f:.5f,rectangle?0.f:.75f,1.f},rectangle?.375f:.75f,0};
    return append(&c,sizeof(c));
}
static int read(uint32_t id,uint32_t plane,void *destination,uint32_t size) {
    return halo_metal_guest_readback(&transport,(struct halo_metal_ref){id,1},plane,destination,size);
}
static int check_pattern(int rectangle) {
    for(uint32_t y=0;y<7;y++)for(uint32_t x=0;x<13;x++) {
        const unsigned char *p=color+(y*13+x)*4;
        int inside=rectangle && x>=3 && x<7 && y>=2 && y<5;
        if(p[0]!=(inside?0u:41u+x) || p[1]!=(inside?255u:21u+y) || p[2]!=(inside?0u:109u) || p[3]!=255u)return 0;
    }
    return 1;
}
int guest_test(void) {
    int reply_guards=halo_transport_reply_guards();
    if(reply_guards)return failed((uint32_t)reply_guards);
    halo_transport_report[6]=18;
    int alpha_border_guards=halo_transport_alpha_border_guards();
    if(alpha_border_guards)return failed((uint32_t)alpha_border_guards);
    halo_transport_report[7]=8;
    struct halo_metal_guest_transport bad;
    memset(storage,0xa5,sizeof(storage));
    if(halo_metal_guest_setup(&bad,storage+1,sizeof(storage)-1)!=HALO_METAL_INVALID) return 101;
    if(halo_metal_guest_setup(&bad,storage,HALO_METAL_MAX_PACKET+1)!=HALO_METAL_INVALID) return 102;
    if(halo_metal_guest_setup(&transport,storage,sizeof(storage))) return 103;
    if(halo_metal_guest_initialize(&transport,1,HALO_METAL_OFFSCREEN,31)!=HALO_METAL_INVALID) return failed(104);
    if(halo_metal_guest_initialize(&transport,0,HALO_METAL_OFFSCREEN,UINT32_C(0x80000000))!=HALO_METAL_UNSUPPORTED) return failed(105);
    if(halo_metal_guest_initialize(&transport,0,HALO_METAL_OFFSCREEN,HALO_METAL_CAP_PRESENT_EXACT)!=HALO_METAL_UNSUPPORTED || transport.initialized) return failed(106);
    if(halo_metal_guest_initialize(&transport,0,HALO_METAL_OFFSCREEN,31)) return failed(107);
    if(transport.reply.capabilities&HALO_METAL_CAP_PRESENT_EXACT) return failed(108);
    halo_transport_report[1]=3;
    if(halo_metal_guest_begin(&transport,1) || create(1,HALO_METAL_RGBA8) || create(2,HALO_METAL_DEPTH32_STENCIL8) ||
        create(3,HALO_METAL_RGBA8) || clear(1,0) || halo_metal_guest_submit(&transport)) return failed(109);
    if(transport.reply.submitted_sequence!=1 || transport.reply.completed_sequence!=1 || transport.reply.live_resources!=3) return failed(110);
    if(read(1,HALO_METAL_COLOR,color,sizeof(color)) || read(2,HALO_METAL_DEPTH,depth,sizeof(depth)) ||
        read(2,HALO_METAL_STENCIL,stencil,sizeof(stencil))) return failed(111);
    for(uint32_t i=0;i<13*7;i++)if(color[i*4]!=64 || color[i*4+1]!=128 || color[i*4+2]!=191 || color[i*4+3]!=255 ||
        depth[i]!=.75f || stencil[i]!=17) return failed(112);
    halo_transport_report[1]=6;
    if(halo_metal_guest_begin(&transport,2)) return failed(113);
    memset(upload,0xcd,sizeof(upload));
    for(uint32_t y=0;y<7;y++)for(uint32_t x=0;x<13;x++) {
        unsigned char *p=upload+y*64+x*4;p[0]=41+x;p[1]=21+y;p[2]=109;p[3]=255;
    }
    uint32_t command_offset=UINT32_MAX,data_offset=UINT32_MAX;
    struct halo_metal_upload u={{HALO_METAL_UPLOAD,0},{1,1},0,0,13,7,64,0,sizeof(upload),0};
    if(halo_metal_guest_append_command(&transport,&u,sizeof(u),&command_offset) ||
        halo_metal_guest_append_payload(&transport,upload,sizeof(upload),&data_offset) ||
        halo_metal_guest_patch_u32(&transport,command_offset,offsetof(struct halo_metal_upload,data_offset),data_offset)) return failed(114);
    if(command_offset!=24 || data_offset!=80 || (transport.size&7)) return failed(115);
    for(uint32_t i=72;i<data_offset;i++)if(storage[i]) return failed(116);
    for(uint32_t i=data_offset+sizeof(upload);i<transport.size;i++)if(storage[i]) return failed(117);
    memset(upload,0,sizeof(upload));
    if(storage[data_offset]!=41 || storage[data_offset+64]!=41) return failed(118);
    struct halo_metal_copy copy={{HALO_METAL_COPY,0},{1,1},{3,1},0,0,0,0,13,7};
    if(append(&copy,sizeof(copy)) || halo_metal_guest_submit(&transport)) return failed(119);
    memset(storage,0xee,sizeof(storage));
    if(read(1,HALO_METAL_COLOR,color,sizeof(color)) || !check_pattern(0) || transport.reply.content_version!=2 ||
        read(3,HALO_METAL_COLOR,color,sizeof(color)) || !check_pattern(0) || transport.reply.content_version!=1) return failed(120);
    if(halo_metal_guest_begin(&transport,3) || clear(3,1) || halo_metal_guest_submit(&transport)) return failed(121);
    if(read(3,HALO_METAL_COLOR,color,sizeof(color)) || !check_pattern(1) ||
        read(2,HALO_METAL_DEPTH,depth,sizeof(depth)) || read(2,HALO_METAL_STENCIL,stencil,sizeof(stencil))) return failed(122);
    for(uint32_t y=0;y<7;y++)for(uint32_t x=0;x<13;x++) {
        int inside=x>=3&&x<7&&y>=2&&y<5;
        if(depth[y*13+x]!=(inside?.375f:.75f) || stencil[y*13+x]!=(inside?9:17)) return failed(123);
    }
    halo_transport_report[1]=10;
    if(halo_metal_guest_begin(&transport,3)!=HALO_METAL_INVALID || halo_metal_guest_begin(&transport,0)!=HALO_METAL_INVALID) return failed(124);
    if(halo_metal_guest_begin(&transport,4)) return failed(125);
    uint32_t untouched=UINT32_MAX;
    if(halo_metal_guest_append_payload(&transport,upload,4,&untouched)!=HALO_METAL_INVALID || untouched!=UINT32_MAX ||
        halo_metal_guest_submit(&transport)!=HALO_METAL_INVALID || transport.reply.submitted_sequence!=3) return failed(126);
    if(halo_metal_guest_begin(&transport,4)) return failed(127);
    struct halo_metal_command unknown={0xffffu,8};
    if(halo_metal_guest_append_command(&transport,&unknown,sizeof(unknown),&untouched)!=HALO_METAL_UNSUPPORTED ||
        transport.size!=24 || transport.command_count || untouched!=UINT32_MAX) return failed(128);
    if(halo_metal_guest_begin(&transport,4) || halo_metal_guest_append_command(&transport,&u,sizeof(u),&command_offset)) return failed(129);
    uint32_t old_size=transport.size;
    if(halo_metal_guest_append_payload(&transport,upload,UINT32_MAX,&untouched)!=HALO_METAL_MEMORY ||
        transport.size!=old_size || untouched!=UINT32_MAX || halo_metal_guest_submit(&transport)!=HALO_METAL_MEMORY) return failed(130);
    if(halo_metal_guest_begin(&transport,4) || halo_metal_guest_append_command(&transport,&u,sizeof(u),&command_offset)) return failed(131);
    if(halo_metal_guest_patch_u32(&transport,command_offset,4,123)!=HALO_METAL_INVALID) return failed(132);
    if(halo_metal_guest_begin(&transport,4) || halo_metal_guest_submit(&transport)!=HALO_METAL_INVALID) return failed(133);
    /* Real host preflight rejects a later invalid resource without executing
       the earlier clear. The same submitted sequence can then be retried. */
    if(halo_metal_guest_begin(&transport,4) || clear(3,0) || create(4,99)) return failed(134);
    if(halo_metal_guest_submit(&transport)!=HALO_METAL_UNSUPPORTED || transport.reply.failed_command!=1 ||
        transport.reply.submitted_sequence!=3 || transport.reply.completed_sequence!=3 || transport.reply.live_resources!=3) return failed(135);
    if(read(3,HALO_METAL_COLOR,color,sizeof(color)) || !check_pattern(1) || transport.reply.content_version!=2) return failed(136);
    if(read(2,HALO_METAL_DEPTH,depth,sizeof(depth)) || read(2,HALO_METAL_STENCIL,stencil,sizeof(stencil))) return failed(137);
    for(uint32_t y=0;y<7;y++)for(uint32_t x=0;x<13;x++) {
        int inside=x>=3&&x<7&&y>=2&&y<5;
        if(depth[y*13+x]!=(inside?.375f:.75f) || stencil[y*13+x]!=(inside?9:17)) return failed(138);
    }
    uint64_t high_sequence=(UINT64_C(1)<<32)+7;
    if(halo_metal_guest_begin(&transport,high_sequence) || create(4,HALO_METAL_RGBA8) || halo_metal_guest_submit(&transport) ||
        transport.reply.submitted_sequence!=high_sequence || transport.reply.completed_sequence!=high_sequence) return failed(139);
    if(read(4,HALO_METAL_COLOR,color,sizeof(color))!=HALO_METAL_UNDEFINED_CONTENT) return failed(140);
    halo_transport_report[1]=18;halo_transport_report[4]=7;halo_transport_report[5]=1;
    halo_metal_guest_shutdown(&transport);
    if(read(1,HALO_METAL_COLOR,color,sizeof(color))!=HALO_METAL_NOT_INITIALIZED) return failed(141);
    halo_transport_report[1]=19;halo_transport_report[0]=0;return 0;
}
