/* Ordered original attachment diagnostic through actual rebased ILP32 imports.
 * The guest contains packets and readback metadata, never expected attachments.
 */
#include "../include/halo_metal_abi.h"
#include "metal_host_frame_fixture.h"
_Static_assert(sizeof(void *) == 4,"guest pointer layout");
struct frame_step { uint32_t packet,bytes,event,first_readback,readback_count; };
struct frame_readback { uint32_t resource,plane,bytes,target_id,version,width,height; };
extern const struct frame_step halo_frame_steps[HALO_FRAME_STEPS];
extern const struct frame_readback halo_frame_readbacks[HALO_FRAME_READBACKS];
extern int host_frame_checkpoint(uint32_t event,uint32_t metadata,uint32_t data,uint32_t reply);
unsigned char halo_frame_scratch[HALO_FRAME_SCRATCH];
uint32_t halo_frame_report[16];
static struct halo_metal_reply response;
void *memcpy(void *destination,const void *source,unsigned long count) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(unsigned long i=0;i<count;i++)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,unsigned long count) {
    unsigned char *d=destination;for(unsigned long i=0;i<count;i++)d[i]=value;return destination;
}
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static uint32_t failure(int status,uint32_t code) {
    halo_frame_report[2]=(uint32_t)status;halo_frame_report[3]=response.failed_command;
    host_metal_shutdown();return code;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused;halo_frame_report[0]=1;halo_frame_report[1]=1;
    halo_frame_report[6]=HALO_FRAME_STEPS;halo_frame_report[7]=HALO_FRAME_READBACKS;
    halo_frame_report[8]=HALO_FRAME_SOURCE_FRAME;halo_frame_report[9]=HALO_FRAME_ATTACHMENTS_ONLY;
    int status=host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&response),sizeof(response));
    if(status)return failure(status,101);
    uint32_t required=95u|(HALO_FRAME_NATIVE_QUERIES?HALO_METAL_CAP_VISIBILITY:0u);
    if((response.capabilities & required)!=required)return failure(HALO_METAL_UNSUPPORTED,102);
    uint32_t submitted=0;
    for(uint32_t step=0;step<HALO_FRAME_STEPS;step++) {
        const struct frame_step *s=&halo_frame_steps[step];
        halo_frame_report[1]=2;halo_frame_report[10]=step;halo_frame_report[11]=s->event;
        if(s->bytes) {
            status=host_metal_submit(s->packet,s->bytes,address(&response),sizeof(response));
            if(status)return failure(status,103);
            submitted++;
        }
        halo_frame_report[4]=(uint32_t)response.completed_sequence;
        halo_frame_report[5]=(uint32_t)(response.completed_sequence>>32);
        if(response.completed_sequence!=submitted)return failure(HALO_METAL_INVALID,104);
        for(uint32_t index=0;index<s->readback_count;index++) {
            const struct frame_readback *r=&halo_frame_readbacks[s->first_readback+index];
            if(r->bytes>sizeof(halo_frame_scratch))return failure(HALO_METAL_MEMORY,105);
            halo_frame_report[1]=3;halo_frame_report[12]=s->first_readback+index;
            status=host_metal_readback(r->resource,1,r->plane,address(halo_frame_scratch),r->bytes,address(&response),sizeof(response));
            if(status)return failure(status,106);
            if(r->plane==HALO_METAL_VISIBILITY)halo_frame_report[15]++;
            status=host_frame_checkpoint(s->event,address(r),address(halo_frame_scratch),address(&response));
            if(status)return failure(status,107);
            halo_frame_report[13]++;
        }
        halo_frame_report[14]++;
    }
    host_metal_shutdown();halo_frame_report[1]=4;return 0;
}
