/* Independent copy test. All packets are assembled by the production ILP32
 * C transport. GPU readbacks, never reference images, supply atomic baselines. */
#include "../../linux/src/metal_guest_transport.h"
#include "metal_copy_subresource_fixture.h"
_Static_assert(sizeof(void *) == 4, "copy fixture requires actual ILP32");
struct action { uint32_t word[12]; };
extern const struct action halo_copy_actions[HALO_COPY_ACTIONS];
extern const unsigned char halo_copy_inputs[HALO_COPY_INPUT_BYTES];
extern int host_frame_checkpoint(uint32_t, uint32_t, uint32_t, uint32_t);
static unsigned char packet[HALO_COPY_PACKET_CAPACITY] __attribute__((aligned(16)));
static unsigned char scratch[65536], saved[6][65536];
static uint32_t saved_sizes[6], saved_versions[6];
uint32_t halo_frame_report[16];
static struct halo_metal_guest_transport transport;
void *memcpy(void *destination, const void *source, unsigned long count) {
    unsigned char *d=destination; const unsigned char *s=source;
    for(unsigned long i=0;i<count;i++) d[i]=s[i]; return destination;
}
void *memset(void *destination, int value, unsigned long count) {
    unsigned char *d=destination; for(unsigned long i=0;i<count;i++) d[i]=(unsigned char)value; return destination;
}
static uint32_t address(const void *p) { return (uint32_t)(uintptr_t)p; }
static uint32_t fail(uint32_t index, int status) {
    halo_frame_report[2]=index; halo_frame_report[3]=(uint32_t)status;
    halo_frame_report[4]=transport.reply.failed_command;
    halo_metal_guest_shutdown(&transport); return 100+index;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused; halo_frame_report[0]=1; halo_frame_report[1]=1;
    int status=halo_metal_guest_setup(&transport,packet,sizeof(packet));
    if(status) return fail(0,status);
    status=halo_metal_guest_initialize(&transport,0,HALO_METAL_OFFSCREEN,HALO_COPY_REQUIRED_CAPS);
    if(status) return fail(0,status);
    for(uint32_t index=0;index<HALO_COPY_ACTIONS;index++) {
        const uint32_t *a=halo_copy_actions[index].word; halo_frame_report[5]=index;
        if(a[0]==1) { /* Begin the next sequence, including after a rejected packet. */
            status=halo_metal_guest_begin(&transport,transport.reply.submitted_sequence+1);
        } else if(a[0]==2) { /* Immutable fixed metadata plus payload descriptors. */
            uint32_t command;
            if(a[1]>HALO_COPY_INPUT_BYTES || a[2]>HALO_COPY_INPUT_BYTES-a[1] ||
               a[3]>HALO_COPY_INPUT_BYTES || a[4]>4 || a[4]*12>HALO_COPY_INPUT_BYTES-a[3]) return fail(index,-1);
            status=halo_metal_guest_append_command(&transport,halo_copy_inputs+a[1],a[2],&command);
            for(uint32_t p=0;!status && p<a[4];p++) {
                uint32_t d[3],offset; memcpy(d,halo_copy_inputs+a[3]+p*12,sizeof(d));
                if(d[1]>HALO_COPY_INPUT_BYTES || d[2]>HALO_COPY_INPUT_BYTES-d[1]) return fail(index,-1);
                status=halo_metal_guest_append_payload(&transport,halo_copy_inputs+d[1],d[2],&offset);
                if(!status) status=halo_metal_guest_patch_u32(&transport,command,d[0],offset);
            }
        } else if(a[0]==3) { /* Submit; failed preflight must not commit anything. */
            struct halo_metal_reply before=transport.reply;
            status=halo_metal_guest_submit(&transport);
            if(a[1]) {
                if(status!=(int)a[1] || transport.reply.failed_command!=a[2] ||
                   transport.reply.submitted_sequence!=before.submitted_sequence ||
                   transport.reply.completed_sequence!=before.completed_sequence ||
                   transport.reply.live_resources!=before.live_resources || transport.poisoned) return fail(index,status?status:-1);
                halo_frame_report[7]++; status=0;
            } else if(!status) halo_frame_report[6]++;
        } else if(a[0]==4) { /* Read/export; optionally save or compare actual baseline. */
            struct halo_metal_ref ref={a[1],a[2]};
            if(a[4]>sizeof(scratch) || a[10]>=6) return fail(index,-1);
            status=halo_metal_guest_readback(&transport,ref,a[3],scratch,a[4]);
            if(!status && transport.reply.content_version!=a[8]) return fail(index,-1);
            if(!status && a[9]==1) {
                memcpy(saved[a[10]],scratch,a[4]); saved_sizes[a[10]]=a[4]; saved_versions[a[10]]=transport.reply.content_version;
            } else if(!status && a[9]==2) {
                if(saved_sizes[a[10]]!=a[4] || saved_versions[a[10]]!=transport.reply.content_version) return fail(index,-1);
                for(uint32_t p=0;p<a[4];p++) if(saved[a[10]][p]!=scratch[p]) return fail(index,-1);
                halo_frame_report[9]++;
            }
            if(!status) {
                uint32_t metadata[7]={a[1],a[3],a[4],a[1],a[8],a[5],a[6]};
                status=host_frame_checkpoint(a[7],address(metadata),address(scratch),address(&transport.reply));
                if(!status) halo_frame_report[8]++;
            }
        } else return fail(index,-1);
        if(status) return fail(index,status);
    }
    halo_frame_report[10]=(uint32_t)transport.reply.completed_sequence;
    halo_frame_report[11]=transport.reply.live_resources;
    halo_metal_guest_shutdown(&transport); halo_frame_report[1]=4; return 0;
}
