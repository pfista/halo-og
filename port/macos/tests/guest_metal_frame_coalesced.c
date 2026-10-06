/* Test-only ordered-frame coalescing. Original GPU commands submit once;
 * final readback expectations remain exclusively in host CPU comparison. */
#include "../include/halo_metal_abi.h"
#include "metal_host_frame_coalesced_fixture.h"
_Static_assert(sizeof(void *)==4,"actual coalesced ILP32 guest");
struct final_readback {
    uint32_t event;
    struct { uint32_t resource,plane,bytes,target_id,version,width,height; } metadata;
    uint32_t expected_wire_version;
};
extern const unsigned char halo_coalesced_packet[HALO_COALESCED_PACKET_BYTES];
extern const struct final_readback halo_coalesced_readbacks[HALO_COALESCED_READBACKS];
extern int host_frame_checkpoint(uint32_t,uint32_t,uint32_t,uint32_t);
unsigned char halo_frame_scratch[HALO_COALESCED_SCRATCH];
uint32_t halo_frame_report[16];
static struct halo_metal_reply response;
void *memcpy(void *destination,const void *source,unsigned long count) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(unsigned long i=0;i<count;i++)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,unsigned long count) {
    unsigned char *d=destination;for(unsigned long i=0;i<count;i++)d[i]=(unsigned char)value;return destination;
}
static uint32_t address(const void *p){return (uint32_t)(uintptr_t)p;}
static uint32_t failure(int status,uint32_t code) {
    halo_frame_report[2]=(uint32_t)status;halo_frame_report[3]=response.failed_command;
    host_metal_shutdown();return code;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;halo_frame_report[0]=1;halo_frame_report[1]=1;
    halo_frame_report[6]=HALO_COALESCED_DRAWS;halo_frame_report[7]=HALO_COALESCED_READBACKS;
    halo_frame_report[8]=HALO_COALESCED_SOURCE_FRAME;halo_frame_report[9]=HALO_COALESCED_ORIGINAL_PACKETS;
    halo_frame_report[10]=HALO_COALESCED_COMMANDS;halo_frame_report[13]=HALO_COALESCED_PACKET_BYTES;
    int status=host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&response),sizeof(response));
    if(status)return failure(status,101);
    uint32_t required=95u|HALO_METAL_CAP_VISIBILITY;
    if(response.abi_version!=1 || (response.capabilities&required)!=required)return failure(HALO_METAL_UNSUPPORTED,102);
    halo_frame_report[1]=2;
    status=host_metal_submit(address(halo_coalesced_packet),sizeof(halo_coalesced_packet),address(&response),sizeof(response));
    if(status)return failure(status,103);
    if(response.submitted_sequence!=1 || response.completed_sequence!=1 || response.failed_command!=UINT32_MAX ||
       response.abi_version!=1 || response.reserved)return failure(HALO_METAL_INVALID,104);
    halo_frame_report[4]=(uint32_t)response.completed_sequence;halo_frame_report[5]=(uint32_t)(response.completed_sequence>>32);
    halo_frame_report[11]=1;halo_frame_report[14]=response.live_resources;
    for(uint32_t index=0;index<HALO_COALESCED_READBACKS;index++) {
        const struct final_readback *r=&halo_coalesced_readbacks[index];
        if(r->metadata.bytes>sizeof(halo_frame_scratch))return failure(HALO_METAL_MEMORY,105);
        halo_frame_report[1]=3;
        status=host_metal_readback(r->metadata.resource,1,r->metadata.plane,address(halo_frame_scratch),r->metadata.bytes,address(&response),sizeof(response));
        if(status)return failure(status,106);
        if(response.byte_size!=r->metadata.bytes || response.content_version!=r->expected_wire_version ||
           response.submitted_sequence!=1 || response.completed_sequence!=1)return failure(HALO_METAL_INVALID,107);
        status=host_frame_checkpoint(r->event,address(&r->metadata),address(halo_frame_scratch),address(&response));
        if(status)return failure(status,108);
        halo_frame_report[12]++;
        if(r->metadata.plane==HALO_METAL_VISIBILITY)halo_frame_report[15]++;
    }
    host_metal_shutdown();halo_frame_report[1]=4;return 0;
}
