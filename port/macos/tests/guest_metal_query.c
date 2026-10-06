/* Query lifecycle through the real rebased ILP32 imports. Original opaque
 * DRAW resources/program/payloads are retained; expected after-targets are
 * CPU comparisons only. This does not model original cached CPU polling. */
#include "../include/halo_metal_abi.h"
#include "metal_host_query_fixture.h"
_Static_assert(sizeof(void *) == 4, "guest pointer layout");
extern const unsigned char halo_draw_packet[HALO_QUERY_PACKET_BYTES];
extern const unsigned char halo_query_single[HALO_QUERY_SINGLE_BYTES];
extern const unsigned char halo_query_occluded[HALO_QUERY_SINGLE_BYTES];
extern const unsigned char halo_query_double[HALO_QUERY_DOUBLE_BYTES];
extern const unsigned char halo_query_invalid_later[HALO_QUERY_DOUBLE_BYTES];
extern const unsigned char halo_draw_expected_color[HALO_QUERY_COLOR_BYTES];
extern const unsigned char halo_draw_expected_depth[HALO_QUERY_DEPTH_BYTES];
extern const unsigned char halo_draw_expected_stencil[HALO_QUERY_STENCIL_BYTES];
unsigned char halo_draw_actual_color[HALO_QUERY_COLOR_BYTES];
unsigned char halo_draw_actual_depth[HALO_QUERY_DEPTH_BYTES];
unsigned char halo_draw_actual_stencil[HALO_QUERY_STENCIL_BYTES];
/* Raw 64B query report, deliberately different from the old driver's labels:
 * ABI,phase,status,failed_command,cases,invariant_checks,single_count(lo/hi),
 * double_count(lo/hi),visible_boolean,multi_boolean,empty_count,width,height,
 * original_packet_bytes. Consumers must decode these raw words themselves. */
uint32_t halo_draw_report[16];
static struct halo_metal_reply response;
static uint64_t sequence, query_value;
static uint32_t versions[3], query_versions[2], live;
static unsigned char mini[96] __attribute__((aligned(16)));
static unsigned char single[HALO_QUERY_SINGLE_BYTES] __attribute__((aligned(16)));
static unsigned char double_draw[HALO_QUERY_DOUBLE_BYTES] __attribute__((aligned(16)));
static uint32_t mini_bytes,mini_count;
enum { QUERY_CREATE=HALO_METAL_CREATE_VISIBILITY,QUERY_DELETE=HALO_METAL_DELETE_VISIBILITY,
    QUERY_BEGIN=HALO_METAL_BEGIN_VISIBILITY,QUERY_END=HALO_METAL_END_VISIBILITY,
    QUERY_PLANE=HALO_METAL_VISIBILITY,QUERY_CAP=HALO_METAL_CAP_VISIBILITY };

void *memcpy(void *dst,const void *src,unsigned long bytes) {
    unsigned char *d=dst;const unsigned char *s=src;for(unsigned long i=0;i<bytes;i++)d[i]=s[i];return dst;
}
void *memset(void *dst,int value,unsigned long bytes) {
    unsigned char *d=dst;for(unsigned long i=0;i<bytes;i++)d[i]=value;return dst;
}
static uint32_t address(const void *p) {return (uint32_t)(uintptr_t)p;}
static int fail(int status,uint32_t code) {
    halo_draw_report[2]=(uint32_t)status;halo_draw_report[3]=response.failed_command;
    host_metal_shutdown();return (int)code;
}
static void mark(uint32_t bit) {halo_draw_report[4]|=1u<<bit;}
static int send(void *packet,uint32_t bytes,int expected,uint32_t failed) {
    struct halo_metal_packet *header=packet;header->frame_sequence=sequence+1;
    int status=host_metal_submit(address(packet),bytes,address(&response),sizeof(response));
    if(status!=expected || response.status!=expected ||
        response.failed_command!=failed)return fail(status,200+halo_draw_report[1]);
    if(status==HALO_METAL_OK)sequence++;
    if(response.submitted_sequence!=sequence || response.completed_sequence!=sequence)
        return fail(HALO_METAL_INVALID,250+halo_draw_report[1]);
    if(status && response.live_resources!=live)return fail(HALO_METAL_INVALID,300+halo_draw_report[1]);
    if(!status)live=response.live_resources;
    return 0;
}
static void start(void) {memset(mini,0,sizeof(mini));mini_bytes=24;mini_count=0;}
static void append(uint32_t op,uint32_t id,uint32_t generation,uint32_t mode,uint32_t reserved) {
    struct halo_metal_create_visibility cmd={{op,op==QUERY_CREATE?24:16},{id,generation},mode,reserved};
    memcpy(mini+mini_bytes,&cmd,cmd.command.byte_size);mini_bytes+=cmd.command.byte_size;mini_count++;
}
static int finish(int expected,uint32_t failed) {
    struct halo_metal_packet header={HALO_METAL_MAGIC,HALO_METAL_ABI_VERSION,mini_bytes,mini_count,sequence+1};
    memcpy(mini,&header,24);return send(mini,mini_bytes,expected,failed);
}
static int operation(uint32_t op,uint32_t id,uint32_t generation,uint32_t mode,int expected) {
    start();append(op,id,generation,mode,0);int error=finish(expected,expected?0:UINT32_MAX);
    if(!error && !expected && id>=200 && id<=201) {
        if(op==QUERY_CREATE)query_versions[id-200]=0;
        if(op==QUERY_END)query_versions[id-200]++;
    }
    return error;
}
static int original_draw(const unsigned char *source,uint32_t bytes) {
    unsigned char *destination=bytes==HALO_QUERY_SINGLE_BYTES?single:double_draw;
    memcpy(destination,source,bytes);return send(destination,bytes,HALO_METAL_OK,UINT32_MAX);
}
static int read_all(void) {
    const uint32_t ids[3]={1,2,2},planes[3]={HALO_METAL_COLOR,HALO_METAL_DEPTH,HALO_METAL_STENCIL};
    unsigned char *dest[3]={halo_draw_actual_color,halo_draw_actual_depth,halo_draw_actual_stencil};
    const uint32_t sizes[3]={HALO_QUERY_COLOR_BYTES,HALO_QUERY_DEPTH_BYTES,HALO_QUERY_STENCIL_BYTES};
    for(uint32_t i=0;i<3;i++) {
        int status=host_metal_readback(ids[i],1,planes[i],address(dest[i]),sizes[i],address(&response),sizeof(response));
        if(status || response.byte_size!=sizes[i] || response.submitted_sequence!=sequence ||
           response.completed_sequence!=sequence || response.live_resources!=live)return fail(status,400+i);
        if(versions[i] && response.content_version!=versions[i])return fail(HALO_METAL_INVALID,410+i);
        versions[i]=response.content_version;
    }
    static const unsigned char channels[4]={2,1,0,3};
    for(uint32_t i=0;i<HALO_QUERY_COLOR_BYTES;i++)
        if(halo_draw_actual_color[(i&~3u)+channels[i&3u]]!=halo_draw_expected_color[i])return fail(HALO_METAL_INVALID,420);
    for(uint32_t i=0;i<HALO_QUERY_DEPTH_BYTES;i++)
        if(halo_draw_actual_depth[i]!=halo_draw_expected_depth[i])return fail(HALO_METAL_INVALID,421);
    for(uint32_t i=0;i<HALO_QUERY_STENCIL_BYTES;i++)
        if(halo_draw_actual_stencil[i]!=halo_draw_expected_stencil[i])return fail(HALO_METAL_INVALID,422);
    halo_draw_report[5]++;return 0;
}
static int result(uint32_t id,uint32_t generation,int expected) {
    const uint64_t canary=UINT64_C(0xc5371298a6de40bf);query_value=canary;
    int status=host_metal_readback(id,generation,QUERY_PLANE,address(&query_value),8,address(&response),sizeof(response));
    if(status!=expected || response.status!=expected || response.submitted_sequence!=sequence ||
       response.completed_sequence!=sequence || response.live_resources!=live)return fail(status,430);
    if(!status && (response.byte_size!=8 || id<200 || id>201 ||
        response.content_version!=query_versions[id-200]))return fail(HALO_METAL_INVALID,431);
    if(status && query_value!=canary)return fail(HALO_METAL_INVALID,432);
    return 0;
}
#define TRY(expr) do {int error=(expr);if(error)return (uint32_t)error;} while(0)
#define EXPECT(value,code) do {if(!(value))return (uint32_t)fail(HALO_METAL_INVALID,code);} while(0)
uint32_t guest_test(uint32_t unused) {
    (void)unused;halo_draw_report[0]=HALO_METAL_ABI_VERSION;halo_draw_report[1]=1;
    halo_draw_report[13]=HALO_QUERY_WIDTH;halo_draw_report[14]=HALO_QUERY_HEIGHT;halo_draw_report[15]=HALO_QUERY_PACKET_BYTES;
    int status=host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&response),sizeof(response));
    if(status)return (uint32_t)fail(status,101);
    EXPECT((response.capabilities&(QUERY_CAP|HALO_METAL_CAP_DRAW|HALO_METAL_CAP_READBACK))==
        (QUERY_CAP|HALO_METAL_CAP_DRAW|HALO_METAL_CAP_READBACK),102);mark(0);
    status=host_metal_submit(address(halo_draw_packet),HALO_QUERY_PACKET_BYTES,address(&response),sizeof(response));
    if(status)return (uint32_t)fail(status,103);
    sequence=1;live=response.live_resources;EXPECT(response.completed_sequence==sequence && response.submitted_sequence==sequence,104);
    TRY(read_all());mark(1);uint32_t original_live=live;
    halo_draw_report[1]=2;
    TRY(operation(QUERY_CREATE,200,1,1,HALO_METAL_OK));TRY(operation(QUERY_CREATE,201,1,2,HALO_METAL_OK));
    EXPECT(live==original_live+2,105);
    TRY(operation(QUERY_BEGIN,200,1,0,HALO_METAL_OK));TRY(operation(QUERY_END,200,1,0,HALO_METAL_OK));
    TRY(result(200,1,HALO_METAL_OK));EXPECT(query_value==0,106);mark(2);
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));
    TRY(result(201,1,HALO_METAL_OK));EXPECT(query_value==0,107);mark(3);TRY(read_all());
    halo_draw_report[1]=3;
    TRY(operation(QUERY_BEGIN,200,1,0,HALO_METAL_OK));
    TRY(result(200,1,HALO_METAL_UNDEFINED_CONTENT));mark(4);
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_INVALID));mark(5);
    TRY(operation(QUERY_END,201,1,0,HALO_METAL_INVALID));mark(6);
    TRY(operation(QUERY_DELETE,200,1,0,HALO_METAL_INVALID));mark(7);
    TRY(operation(QUERY_END,200,2,0,HALO_METAL_STALE_RESOURCE));mark(8);
    TRY(original_draw(halo_query_single,HALO_QUERY_SINGLE_BYTES));
    TRY(operation(QUERY_END,200,1,0,HALO_METAL_OK));TRY(result(200,1,HALO_METAL_OK));
    EXPECT(query_value==1,108);halo_draw_report[10]=(uint32_t)query_value;mark(9);TRY(read_all());
    TRY(operation(QUERY_BEGIN,200,1,0,HALO_METAL_OK));TRY(original_draw(halo_query_single,HALO_QUERY_SINGLE_BYTES));
    TRY(original_draw(halo_query_occluded,HALO_QUERY_SINGLE_BYTES));TRY(operation(QUERY_END,200,1,0,HALO_METAL_OK));
    TRY(result(200,1,HALO_METAL_OK));EXPECT(query_value==1,109);halo_draw_report[11]=(uint32_t)query_value;mark(10);TRY(read_all());
    halo_draw_report[1]=4;
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));TRY(original_draw(halo_query_single,HALO_QUERY_SINGLE_BYTES));
    TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));TRY(result(201,1,HALO_METAL_OK));
    uint64_t one=query_value;EXPECT(one && one<=UINT64_MAX/2,110);
    halo_draw_report[6]=(uint32_t)one;halo_draw_report[7]=(uint32_t)(one>>32);mark(11);TRY(read_all());
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));TRY(original_draw(halo_query_single,HALO_QUERY_SINGLE_BYTES));
    TRY(original_draw(halo_query_single,HALO_QUERY_SINGLE_BYTES));TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));
    TRY(result(201,1,HALO_METAL_OK));EXPECT(query_value==2*one,111);
    halo_draw_report[8]=(uint32_t)query_value;halo_draw_report[9]=(uint32_t)(query_value>>32);mark(12);TRY(read_all());
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));TRY(original_draw(halo_query_double,HALO_QUERY_DOUBLE_BYTES));
    TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));TRY(result(201,1,HALO_METAL_OK));EXPECT(query_value==2*one,112);mark(13);TRY(read_all());
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));
    TRY(result(201,1,HALO_METAL_OK));EXPECT(query_value==0,113);halo_draw_report[12]=0;mark(14);TRY(read_all());
    halo_draw_report[1]=5;
    TRY(operation(QUERY_BEGIN,201,1,0,HALO_METAL_OK));
    memcpy(double_draw,halo_query_invalid_later,HALO_QUERY_DOUBLE_BYTES);
    TRY(send(double_draw,HALO_QUERY_DOUBLE_BYTES,HALO_METAL_INVALID,1));mark(15);TRY(read_all());
    TRY(operation(QUERY_END,201,1,0,HALO_METAL_OK));TRY(result(201,1,HALO_METAL_OK));EXPECT(query_value==0,114);mark(16);
    TRY(operation(QUERY_END,201,1,0,HALO_METAL_INVALID));mark(17);
    TRY(operation(QUERY_CREATE,202,1,3,HALO_METAL_UNSUPPORTED));mark(18);
    start();append(QUERY_CREATE,202,1,1,1);TRY(finish(HALO_METAL_INVALID,0));mark(19);
    halo_draw_report[1]=6;
    TRY(operation(QUERY_DELETE,200,1,0,HALO_METAL_OK));TRY(operation(QUERY_BEGIN,200,1,0,HALO_METAL_STALE_RESOURCE));mark(20);
    TRY(operation(QUERY_CREATE,200,1,1,HALO_METAL_STALE_RESOURCE));mark(21);
    TRY(operation(QUERY_CREATE,200,2,1,HALO_METAL_OK));
    TRY(operation(QUERY_BEGIN,200,1,0,HALO_METAL_STALE_RESOURCE));TRY(result(200,1,HALO_METAL_STALE_RESOURCE));mark(23);
    TRY(operation(QUERY_BEGIN,200,2,0,HALO_METAL_OK));TRY(operation(QUERY_END,200,2,0,HALO_METAL_OK));
    TRY(result(200,2,HALO_METAL_OK));EXPECT(query_value==0,115);mark(22);
    TRY(operation(QUERY_DELETE,200,2,0,HALO_METAL_OK));TRY(operation(QUERY_DELETE,201,1,0,HALO_METAL_OK));
    EXPECT(live==original_live,116);mark(24);TRY(read_all());mark(25);
    host_metal_shutdown();halo_draw_report[1]=7;halo_draw_report[2]=0;halo_draw_report[3]=UINT32_MAX;return 0;
}
