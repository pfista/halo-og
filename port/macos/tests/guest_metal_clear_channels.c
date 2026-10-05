/* Independent patterned attachment expectations through actual ILP32 imports. */
#include "../include/halo_metal_abi.h"
_Static_assert(sizeof(void *) == 4, "actual ILP32 guest");
_Static_assert(sizeof(struct halo_metal_clear_channels) == 80, "channel clear ABI");
enum { W=13, H=7, N=W*H };
unsigned char halo_clear_color[N*4], halo_clear_stencil[N];
float halo_clear_depth[N];
uint32_t halo_clear_report[16];
static unsigned char packet[4096];
static struct halo_metal_reply reply;
static uint32_t position, commands;
static uint64_t sequence;
void *memcpy(void *d,const void *s,unsigned long n) { unsigned char *a=d;const unsigned char *b=s;for(unsigned long i=0;i<n;i++)a[i]=b[i];return d; }
void *memset(void *d,int v,unsigned long n) { unsigned char *a=d;for(unsigned long i=0;i<n;i++)a[i]=v;return d; }
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static void start(void) { position=24;commands=0; }
static void append(const void *c,uint32_t n) { memcpy(packet+position,c,n);position+=n;commands++; }
static int submit(void) {
    struct halo_metal_packet p={HALO_METAL_MAGIC,1,position,commands,sequence+1};memcpy(packet,&p,24);
    int r=host_metal_submit(address(packet),position,address(&reply),sizeof(reply));
    halo_clear_report[2]=(uint32_t)r;halo_clear_report[3]=reply.failed_command;
    if(!r)sequence++;
    return r;
}
static void create(uint32_t id,uint32_t format) {
    struct halo_metal_create c={{HALO_METAL_CREATE_TEXTURE,sizeof(c)},{id,1},format,W,H,0};append(&c,sizeof(c));
}
static unsigned char seed_channel(unsigned x,unsigned y,unsigned channel) {
    const unsigned values[4]={17+x,33+y,71+x+y,90+x+2*y};return (unsigned char)values[channel];
}
static void upload(uint32_t id,uint32_t plane,uint32_t format) {
    unsigned pixel=plane==HALO_METAL_STENCIL?1:4,row=W*pixel,bytes=N*pixel;
    uint32_t offset=position;
    struct halo_metal_upload_ex c={{HALO_METAL_UPLOAD_EX,(72+bytes+7)&~7u},{id,1},
        0,0,0,0,0,W,H,1,row,bytes,offset+72,bytes,plane,0};append(&c,sizeof(c));
    for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
        unsigned char *p=packet+offset+72+(y*W+x)*pixel;
        if(plane==HALO_METAL_STENCIL)*p=(unsigned char)(49+x+3*y);
        else if(plane==HALO_METAL_DEPTH){float v=.25f+(float)(y*W+x)/1024;memcpy(p,&v,4);}
        else for(unsigned k=0;k<4;k++)p[k]=seed_channel(x,y,format==HALO_METAL_BGRA8&&!(k&1)?2-k:k);
    }
    position=offset+c.command.byte_size;
}
static int seed(uint32_t format) {
    start();upload(format,HALO_METAL_COLOR,format);upload(3,HALO_METAL_DEPTH,0);upload(3,HALO_METAL_STENCIL,0);
    return submit();
}
static struct halo_metal_clear_channels clear(uint32_t format,uint32_t mask,uint32_t planes,int rect) {
    struct halo_metal_clear_channels c={{{HALO_METAL_CLEAR_CHANNELS,sizeof(c)},
        {planes&1?format:0,planes&1?1:0},{planes&6?3:0,planes&6?1:0},planes,
        rect?3:0,rect?2:0,rect?4:W,rect?3:H,211,
        {31.f/255,67.f/255,101.f/255,137.f/255},.625f,0},mask,0};return c;
}
static int read(uint32_t id,uint32_t plane,void *p,uint32_t bytes) {
    return host_metal_readback(id,1,plane,address(p),bytes,address(&reply),sizeof(reply));
}
static int check(uint32_t format,uint32_t mask,uint32_t planes,int rect) {
    if(read(format,1,halo_clear_color,sizeof(halo_clear_color)))return 1;
    if(read(3,2,halo_clear_depth,sizeof(halo_clear_depth)))return 2;
    if(read(3,4,halo_clear_stencil,sizeof(halo_clear_stencil)))return 3;
    const unsigned char values[4]={31,67,101,137};
    for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
        unsigned n=y*W+x;int inside=!rect||(x>=3&&x<7&&y>=2&&y<5);
        for(unsigned k=0;k<4;k++){
            unsigned channel=format==HALO_METAL_BGRA8&&!(k&1)?2-k:k;
            unsigned char expected=inside&&(planes&1)&&(mask&(1u<<channel))?values[channel]:seed_channel(x,y,channel);
            if(halo_clear_color[n*4+k]!=expected){halo_clear_report[7]++;return 4;}
        }
        float expected_depth=inside&&(planes&2)?.625f:.25f+(float)n/1024;
        if(halo_clear_depth[n]!=expected_depth){halo_clear_report[8]++;return 5;}
        if(halo_clear_stencil[n]!=(inside&&(planes&4)?211:49+x+3*y)){halo_clear_report[9]++;return 6;}
    }
    halo_clear_report[6]++;return 0;
}
static uint32_t version(uint32_t id) {
    if(read(id,id==3?2:1,id==3?(void*)halo_clear_depth:(void*)halo_clear_color,id==3?sizeof(halo_clear_depth):sizeof(halo_clear_color)))return UINT32_MAX;
    return reply.content_version;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;halo_clear_report[0]=1;halo_clear_report[10]=W;halo_clear_report[11]=H;
    if(host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&reply),sizeof(reply)))return 101;
    halo_clear_report[12]=reply.capabilities;
    if(!(reply.capabilities&HALO_METAL_CAP_CLEAR_CHANNELS))return 102;
    start();create(1,HALO_METAL_RGBA8);create(2,HALO_METAL_BGRA8);create(3,HALO_METAL_DEPTH32_STENCIL8);create(4,HALO_METAL_RGBA8);
    if(submit())return 103;
    for(unsigned format=1;format<=2;format++)for(unsigned planes=1;planes<=7;planes+=2)
    for(unsigned mask=1;mask<=15;mask++)for(unsigned rect=0;rect<=1;rect++){
        halo_clear_report[1]=1000+halo_clear_report[4];
        if(seed(format))return 104;
        uint32_t cv=version(format),dv=version(3);
        struct halo_metal_clear_channels c=clear(format,mask,planes,rect);
        start();append(&c,sizeof(c));if(submit())return 105;
        if(version(format)!=cv+1||version(3)!=dv+((planes&6)!=0))return 106;
        if(check(format,mask,planes,rect))return 107;
        halo_clear_report[4]++;
    }
    for(unsigned planes=2;planes<=6;planes+=2)for(unsigned rect=0;rect<=1;rect++){
        if(seed(1))return 108;uint32_t cv=version(1),dv=version(3);
        struct halo_metal_clear_channels c=clear(1,0,planes,rect);
        start();append(&c,sizeof(c));if(submit())return 109;
        if(version(1)!=cv||version(3)!=dv+1||check(1,0,planes,rect))return 110;
        halo_clear_report[4]++;
    }
    /* Valid first clear must not execute when any later record is invalid. */
    if(seed(1))return 111;
    for(unsigned bad=0;bad<14;bad++){
        halo_clear_report[1]=2000+bad;
        struct halo_metal_clear_channels good=clear(1,15,7,0),c=clear(1,15,7,1);
        int expected=HALO_METAL_INVALID;
        switch(bad){
        case 0:c.color_write_mask=16;break;
        case 1:c.color_write_mask=0;break;
        case 2:c.reserved=1;break;
        case 3:c.clear.reserved=1;break;
        case 4:c.clear.planes=8;break;
        case 5:c.clear.stencil=256;break;
        case 6:c.clear.width=100;break;
        case 7:c.clear.depth=2;break;
        case 8:{uint32_t bits=0x7fc00000;memcpy(&c.clear.rgba[0],&bits,4);break;}
        case 9:c.clear.color.generation=2;expected=HALO_METAL_STALE_RESOURCE;break;
        case 10:c.clear.planes=6;c.clear.color=(struct halo_metal_ref){0,0};break;
        case 11:c.clear.command.byte_size=72;break;
        case 12:c.clear.color=(struct halo_metal_ref){4,1};c.clear.x=c.clear.y=0;c.clear.width=W;c.clear.height=H;c.color_write_mask=1;expected=HALO_METAL_UNDEFINED_CONTENT;break;
        case 13:c.clear.command.opcode=999;expected=HALO_METAL_UNSUPPORTED;break;
        }
        uint32_t cv=version(1),dv=version(3);uint64_t completed=sequence;
        start();append(&good,sizeof(good));append(&c,c.clear.command.byte_size);
        if(submit()!=expected||reply.failed_command!=1||reply.completed_sequence!=completed)return 112;
        if(version(1)!=cv||version(3)!=dv||check(1,0,0,0))return 113;
        halo_clear_report[5]++;
    }
    /* The whole full-mask clear can initialize a previously undefined target. */
    struct halo_metal_clear_channels c=clear(1,15,1,0);c.clear.color.id=4;
    start();append(&c,sizeof(c));if(submit())return 114;
    if(read(4,1,halo_clear_color,sizeof(halo_clear_color)))return 115;
    for(unsigned i=0;i<N;i++)if(halo_clear_color[i*4]!=31||halo_clear_color[i*4+1]!=67||halo_clear_color[i*4+2]!=101||halo_clear_color[i*4+3]!=137)return 116;
    /* Retain final patterned seeds for independent host-side byte checks. */
    if(seed(1)||check(1,0,0,0))return 117;
    halo_clear_report[1]=3000;halo_clear_report[2]=0;halo_clear_report[3]=UINT32_MAX;
    halo_clear_report[13]=(uint32_t)sequence;halo_clear_report[14]=(uint32_t)(sequence>>32);
    halo_clear_report[15]=1;host_metal_shutdown();return 0;
}
