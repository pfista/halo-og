/* One captured Xbox draw, executed through the real rebased ILP32 imports.
 * Expected attachments are comparison inputs only; never GPU upload data. */
#include "../include/halo_metal_abi.h"
#include "metal_host_draw_fixture.h"
_Static_assert(sizeof(void *) == 4, "guest pointer layout");
extern const unsigned char halo_draw_packet[HALO_DRAW_PACKET_BYTES];
extern const unsigned char halo_draw_expected_color[HALO_DRAW_COLOR_BYTES];
extern const unsigned char halo_draw_expected_depth[HALO_DRAW_DEPTH_BYTES];
extern const unsigned char halo_draw_expected_stencil[HALO_DRAW_STENCIL_BYTES];
unsigned char halo_draw_actual_color[HALO_DRAW_COLOR_BYTES];
unsigned char halo_draw_actual_depth[HALO_DRAW_DEPTH_BYTES];
unsigned char halo_draw_actual_stencil[HALO_DRAW_STENCIL_BYTES];
/* Fixed 64B diagnostic contract for the native ELF probe driver. */
uint32_t halo_draw_report[16];
static struct halo_metal_reply response;
#if HALO_DRAW_NEGATIVE_CASES
extern const unsigned char halo_draw_rejection_template[HALO_DRAW_REJECTION_BYTES];
static unsigned char rejection_packet[HALO_DRAW_REJECTION_BYTES] __attribute__((aligned(16)));
static uint32_t attachment_versions[3],live_resources;
#endif

void *memcpy(void *destination,const void *source,unsigned long count) {
    unsigned char *d=destination;const unsigned char *s=source;
    for(unsigned long i=0;i<count;i++)d[i]=s[i];return destination;
}
void *memset(void *destination,int value,unsigned long count) {
    unsigned char *d=destination;for(unsigned long i=0;i<count;i++)d[i]=value;return destination;
}
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static int failure(int status,uint32_t code) {
    halo_draw_report[2]=(uint32_t)status;halo_draw_report[3]=response.failed_command;
    host_metal_shutdown();return (int)code;
}
static int read(uint32_t id,uint32_t plane,void *p,uint32_t size) {
    return host_metal_readback(id,1,plane,address(p),size,address(&response),sizeof(response));
}
static int compare_attachments(void) {
    halo_draw_report[6]=halo_draw_report[7]=halo_draw_report[8]=halo_draw_report[9]=0;
    halo_draw_report[10]=halo_draw_report[11]=halo_draw_report[12]=UINT32_MAX;
    /* Native BGRA target bytes are adapted to reference RGBA for comparison.
     * Rows stay in the captured logical top-left orientation. */
    static const unsigned char channel[4]={2,1,0,3};
    for(uint32_t i=0;i<HALO_DRAW_COLOR_BYTES;i++) {
        unsigned char a=halo_draw_actual_color[(i&~3u)+channel[i&3u]];
        if(a!=halo_draw_expected_color[i]) {
            halo_draw_report[6]++;if(halo_draw_report[10]==UINT32_MAX)halo_draw_report[10]=i;
        }
    }
    for(uint32_t i=0;i<HALO_DRAW_COLOR_BYTES;i+=4)
        if(halo_draw_actual_color[i]!=HALO_DRAW_CLEAR_B || halo_draw_actual_color[i+1]!=HALO_DRAW_CLEAR_G ||
           halo_draw_actual_color[i+2]!=HALO_DRAW_CLEAR_R || halo_draw_actual_color[i+3]!=HALO_DRAW_CLEAR_A)
            halo_draw_report[9]++;
    for(uint32_t i=0;i<HALO_DRAW_DEPTH_BYTES;i++)if(halo_draw_actual_depth[i]!=halo_draw_expected_depth[i]) {
        halo_draw_report[7]++;if(halo_draw_report[11]==UINT32_MAX)halo_draw_report[11]=i;
    }
    for(uint32_t i=0;i<HALO_DRAW_STENCIL_BYTES;i++)if(halo_draw_actual_stencil[i]!=halo_draw_expected_stencil[i]) {
        halo_draw_report[8]++;if(halo_draw_report[12]==UINT32_MAX)halo_draw_report[12]=i;
    }
    if(!halo_draw_report[9])return 108; /* Empty/cull-only draws cannot establish visible fidelity. */
    if(halo_draw_report[6])return 109;
    if(halo_draw_report[7])return 110;
    if(halo_draw_report[8])return 111;
    return 0;
}
#if HALO_DRAW_NEGATIVE_CASES
static int unchanged_reply(uint32_t version) {
    return response.completed_sequence==HALO_DRAW_SEQUENCE && response.submitted_sequence==HALO_DRAW_SEQUENCE &&
           response.live_resources==live_resources && response.content_version==version;
}
static int reject_later_draws(void) {
    _Static_assert(HALO_DRAW_NEGATIVE_CASES==5,"negative fixture contract");
    for(uint32_t test=0;test<HALO_DRAW_NEGATIVE_CASES;test++) {
        halo_draw_report[1]=8+test;
        memcpy(rejection_packet,halo_draw_rejection_template,sizeof(rejection_packet));
        struct halo_metal_draw *draw=(void *)(rejection_packet+HALO_DRAW_REJECTION_DRAW_OFFSET);
        uint32_t poison=UINT32_C(0x7fc00001); /* Quiet NaN. Packed registers are deliberately excluded. */
        if(test==0)draw->state.depth_compare=9;
        if(test==1)memcpy(rejection_packet+draw->indices_offset,&draw->vertex_count,4);
        if(test==2) {
            uint32_t reg=0;while(reg<16 && (draw->packed_mask&(1u<<reg)))reg++;
            if(reg==16)return failure(HALO_METAL_INVALID,120+test*10);
            memcpy(rejection_packet+draw->vertices_offset+reg*16,&poison,4);
        }
        if(test==3)memcpy(rejection_packet+draw->vertex_uniforms_offset,&poison,4);
        if(test==4)memcpy(rejection_packet+draw->pixel_uniforms_offset,&poison,4);
        int status=host_metal_submit(address(rejection_packet),sizeof(rejection_packet),address(&response),sizeof(response));
        halo_draw_report[2]=(uint32_t)status;halo_draw_report[3]=response.failed_command;
        halo_draw_report[4]=(uint32_t)response.completed_sequence;
        halo_draw_report[5]=(uint32_t)(response.completed_sequence>>32);
        if(status!=HALO_METAL_INVALID || response.failed_command!=1 ||
           response.completed_sequence!=HALO_DRAW_SEQUENCE || response.submitted_sequence!=HALO_DRAW_SEQUENCE ||
           response.live_resources!=live_resources)return failure(status,121+test*10);
        status=read(1,HALO_METAL_COLOR,halo_draw_actual_color,sizeof(halo_draw_actual_color));
        if(status || !unchanged_reply(attachment_versions[0]))return failure(status,122+test*10);
        status=read(2,HALO_METAL_DEPTH,halo_draw_actual_depth,sizeof(halo_draw_actual_depth));
        if(status || !unchanged_reply(attachment_versions[1]))return failure(status,123+test*10);
        status=read(2,HALO_METAL_STENCIL,halo_draw_actual_stencil,sizeof(halo_draw_actual_stencil));
        if(status || !unchanged_reply(attachment_versions[2]))return failure(status,124+test*10);
        if(compare_attachments())return failure(HALO_METAL_INVALID,125+test*10);
    }
    halo_draw_report[2]=0;halo_draw_report[3]=UINT32_MAX;
    return 0;
}
#endif
uint32_t guest_test(uint32_t unused) {
    (void)unused;
    halo_draw_report[0]=HALO_METAL_ABI_VERSION;halo_draw_report[1]=1;
    halo_draw_report[10]=halo_draw_report[11]=halo_draw_report[12]=UINT32_MAX;
    halo_draw_report[13]=HALO_DRAW_WIDTH;halo_draw_report[14]=HALO_DRAW_HEIGHT;
    halo_draw_report[15]=HALO_DRAW_PACKET_BYTES;
    int status=host_metal_initialize(0,HALO_METAL_OFFSCREEN,address(&response),sizeof(response));
    if(status)return failure(status,101);
    uint32_t needed=HALO_METAL_CAP_TARGETS|HALO_METAL_CAP_UPLOAD|HALO_METAL_CAP_CLEAR|
                    HALO_METAL_CAP_READBACK|HALO_METAL_CAP_DRAW;
    if(response.abi_version!=HALO_METAL_ABI_VERSION || (response.capabilities&needed)!=needed)
        return failure(HALO_METAL_UNSUPPORTED,102);
    halo_draw_report[1]=2;
    status=host_metal_submit(address(halo_draw_packet),sizeof(halo_draw_packet),address(&response),sizeof(response));
    if(status)return failure(status,103);
    halo_draw_report[4]=(uint32_t)response.completed_sequence;
    halo_draw_report[5]=(uint32_t)(response.completed_sequence>>32);
    if(response.completed_sequence!=HALO_DRAW_SEQUENCE)return failure(HALO_METAL_INVALID,104);
#if HALO_DRAW_NEGATIVE_CASES
    live_resources=response.live_resources;
#endif
    halo_draw_report[1]=3;
    status=read(1,HALO_METAL_COLOR,halo_draw_actual_color,sizeof(halo_draw_actual_color));
    if(status)return failure(status,105);
#if HALO_DRAW_NEGATIVE_CASES
    attachment_versions[0]=response.content_version;
#endif
    halo_draw_report[1]=4;
    status=read(2,HALO_METAL_DEPTH,halo_draw_actual_depth,sizeof(halo_draw_actual_depth));
    if(status)return failure(status,106);
#if HALO_DRAW_NEGATIVE_CASES
    attachment_versions[1]=response.content_version;
#endif
    halo_draw_report[1]=5;
    status=read(2,HALO_METAL_STENCIL,halo_draw_actual_stencil,sizeof(halo_draw_actual_stencil));
    if(status)return failure(status,107);
#if HALO_DRAW_NEGATIVE_CASES
    attachment_versions[2]=response.content_version;
#endif
    halo_draw_report[1]=6;
    status=compare_attachments();if(status)return failure(HALO_METAL_INVALID,status);
#if HALO_DRAW_NEGATIVE_CASES
    status=reject_later_draws();if(status)return status;
#endif
    host_metal_shutdown();halo_draw_report[1]=7;return 0;
}
