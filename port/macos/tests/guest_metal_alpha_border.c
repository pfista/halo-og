#include "../include/halo_metal_abi.h"
#include "metal_host_draw_fixture.h"
#include <stdint.h>
extern int host_metal_initialize(uint32_t,uint32_t,uint32_t,uint32_t);
extern int host_metal_submit(uint32_t,uint32_t,uint32_t,uint32_t);
extern int host_metal_readback(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
extern void host_metal_shutdown(void);
extern const unsigned char halo_draw_packet[HALO_DRAW_PACKET_BYTES];
extern const unsigned char halo_draw_rejection_template[HALO_DRAW_REJECTION_BYTES];
extern const unsigned char halo_draw_expected_color[HALO_DRAW_COLOR_BYTES];
extern const unsigned char halo_draw_expected_depth[HALO_DRAW_DEPTH_BYTES];
extern const unsigned char halo_draw_expected_stencil[HALO_DRAW_STENCIL_BYTES];
extern const unsigned char halo_draw_expected_components[HALO_DRAW_COLOR_BYTES];
unsigned char halo_draw_actual_color[HALO_DRAW_COLOR_BYTES];
unsigned char halo_draw_actual_depth[HALO_DRAW_DEPTH_BYTES];
unsigned char halo_draw_actual_stencil[HALO_DRAW_STENCIL_BYTES];
uint32_t halo_draw_report[16];
static unsigned char rejection[HALO_DRAW_REJECTION_BYTES] __attribute__((aligned(16)));
static struct halo_metal_reply reply;
static uint32_t versions[3],live_resources;
static unsigned char reference_rgb[HALO_DRAW_COLOR_BYTES];
static uint32_t reference_version;
static unsigned char before_color[HALO_DRAW_COLOR_BYTES],before_depth[HALO_DRAW_DEPTH_BYTES],before_stencil[HALO_DRAW_STENCIL_BYTES];
void *memcpy(void *d,const void *s,unsigned long n) { unsigned char *a=d;const unsigned char *b=s;for(unsigned long i=0;i<n;i++)a[i]=b[i];return d; }
void *memset(void *d,int v,unsigned long n) { unsigned char *a=d;for(unsigned long i=0;i<n;i++)a[i]=v;return d; }
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static int fail(int code) { halo_draw_report[2]=(uint32_t)reply.status;halo_draw_report[3]=reply.failed_command;host_metal_shutdown();return code; }
static int attachments(int initial) {
    if(host_metal_readback(31,1,HALO_METAL_COLOR,address(reference_rgb),sizeof(reference_rgb),address(&reply),sizeof(reply)))return 1;
    if(initial)reference_version=reply.content_version;
    else if(reply.content_version!=reference_version || reply.completed_sequence!=1 || reply.submitted_sequence!=1)return 2;
    void *buffers[]={halo_draw_actual_color,halo_draw_actual_depth,halo_draw_actual_stencil};
    uint32_t sizes[]={HALO_DRAW_COLOR_BYTES,HALO_DRAW_DEPTH_BYTES,HALO_DRAW_STENCIL_BYTES};
    const unsigned char *expected[]={halo_draw_expected_color,halo_draw_expected_depth,halo_draw_expected_stencil};
    unsigned char *before[]={before_color,before_depth,before_stencil};
    for(uint32_t aspect=0;aspect<3;aspect++) {
        int status=host_metal_readback(aspect?2:1,1,1u<<aspect,address(buffers[aspect]),sizes[aspect],address(&reply),sizeof(reply));
        if(status)return 1;
        if(initial)versions[aspect]=reply.content_version;
        else if(reply.content_version!=versions[aspect] || reply.completed_sequence!=1 || reply.submitted_sequence!=1 || reply.live_resources!=live_resources)return 2;
        const unsigned char *actual=buffers[aspect];
        if(!initial) {
            for(uint32_t i=0;i<sizes[aspect];i++)if(actual[i]!=before[aspect][i])return 3;
            continue;
        }
        memcpy(before[aspect],actual,sizes[aspect]);
        for(uint32_t i=0;i<sizes[aspect];i++) {
            uint32_t at=i;if(!aspect) { static const unsigned char channels[]={2,1,0,3};at=(i&~3u)+channels[i&3u]; }
            unsigned char wanted=expected[aspect][i];
            if(!aspect && !halo_draw_expected_components[i])wanted=reference_rgb[at];
            if(actual[at]!=wanted) { halo_draw_report[6+aspect]++;if(halo_draw_report[10+aspect]==UINT32_MAX)halo_draw_report[10+aspect]=i; }
        }
    }
    /* Numerical disagreements remain in report6..8 and fail the independent
     * consumer. They do not prevent separate atomic-preflight coverage. */
    return 0;
}
uint32_t guest_test(uint32_t ignored) {
    (void)ignored;halo_draw_report[0]=HALO_METAL_ABI_VERSION;halo_draw_report[1]=1;
    halo_draw_report[10]=halo_draw_report[11]=halo_draw_report[12]=UINT32_MAX;
    halo_draw_report[13]=HALO_DRAW_WIDTH;halo_draw_report[14]=HALO_DRAW_HEIGHT;halo_draw_report[15]=HALO_DRAW_PACKET_BYTES;
    if(host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&reply),sizeof(reply)))return fail(101);
    if(!(reply.capabilities&2048))return fail(102);
    halo_draw_report[5]=reply.capabilities;
    if(host_metal_submit(address(halo_draw_packet),sizeof(halo_draw_packet),address(&reply),sizeof(reply)))return fail(103);
    live_resources=reply.live_resources;
    if(reply.completed_sequence!=1 || attachments(1))return fail(104);
    halo_draw_report[1]=2;
    for(uint32_t test=0;test<13;test++) {
        memcpy(rejection,halo_draw_rejection_template,sizeof(rejection));
        struct halo_metal_draw *draw=(void *)(rejection+HALO_DRAW_REJECTION_DRAW_OFFSET);
        struct halo_metal_draw_alpha_border *extended=(void *)draw;
        int expected=HALO_METAL_INVALID;
        if(test==0)extended->stage_mask=0;
        if(test==1)extended->stage_mask=16;
        if(test==2)extended->reserved=1;
        if(test==3)extended->stage_mask=2; /* Missing texture/companion for stage1. */
        if(test==4) { draw->textures[0].id=11;expected=HALO_METAL_UNSUPPORTED; }
        if(test==5) { draw->samplers[0].max_anisotropy=2;expected=HALO_METAL_UNSUPPORTED; }
        if(test==6) { draw->samplers[0].min_filter=0;expected=HALO_METAL_UNSUPPORTED; }
        if(test==7) { draw->samplers[0].mip_filter=2;expected=HALO_METAL_UNSUPPORTED; }
        if(test==8) { draw->samplers[0].address_u=draw->samplers[0].address_v=2;expected=HALO_METAL_UNSUPPORTED; }
        if(test==9) { float value=.25f;memcpy(rejection+draw->pixel_uniforms_offset+528,&value,4);expected=HALO_METAL_UNSUPPORTED; }
        if(test==10) { float value=2;memcpy(rejection+draw->pixel_uniforms_offset+540,&value,4);expected=HALO_METAL_UNSUPPORTED; }
        if(test==11)draw->program.id=101; /* Legacy shader lacks used companion. */
        if(test==12) { draw->command.opcode=HALO_METAL_DRAW; /* Shader requires unbound companion. */ }
        int status=host_metal_submit(address(rejection),sizeof(rejection),address(&reply),sizeof(reply));
        if(status!=expected || reply.failed_command!=1 || reply.completed_sequence!=1 || reply.submitted_sequence!=1 || reply.live_resources!=live_resources)return fail(110+test);
        if(attachments(0))return fail(120+test);
        halo_draw_report[4]++;
    }
    halo_draw_report[1]=3;halo_draw_report[2]=0;halo_draw_report[3]=UINT32_MAX;
    host_metal_shutdown();return 0;
}
