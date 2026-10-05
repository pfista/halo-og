/* CPU protocol-corruption guards in the real ILP32 guest. The production
 * builder is compiled again with explicit mock imports; no GPU success is
 * inferred from these guards. The independent fixture also executes real GPU
 * resource commands through the original imports. */
#define host_metal_initialize transport_mock_initialize
#define host_metal_submit transport_mock_submit
#define host_metal_readback transport_mock_readback
#define host_metal_shutdown transport_mock_shutdown
#define halo_metal_guest_setup mock_guest_setup
#define halo_metal_guest_initialize mock_guest_initialize
#define halo_metal_guest_begin mock_guest_begin
#define halo_metal_guest_append_command mock_guest_append_command
#define halo_metal_guest_append_payload mock_guest_append_payload
#define halo_metal_guest_patch_u32 mock_guest_patch_u32
#define halo_metal_guest_submit mock_guest_submit
#define halo_metal_guest_readback mock_guest_readback
#define halo_metal_guest_shutdown mock_guest_shutdown
#include "../../linux/src/metal_guest_transport.c"

static unsigned char mock_storage[1024] __attribute__((aligned(16)));
static struct halo_metal_guest_transport mock_transport;
static unsigned int mock_mode, mock_shutdowns, mock_calls;
static uint64_t mock_submitted, mock_completed;
static void mock_reply(uint32_t pointer, int status, uint32_t bytes) {
    struct halo_metal_reply r={HALO_METAL_ABI_VERSION,status,UINT32_MAX,
        ALL_CAPABILITIES & ~(HALO_METAL_CAP_PRESENT_EXACT|HALO_METAL_CAP_PRESENT_SCALED),
        mock_submitted,mock_completed,0,0,bytes,0};
    copy_bytes((void *)(uintptr_t)pointer,&r,sizeof(r));
}
int transport_mock_initialize(uint32_t window,uint32_t flags,uint32_t pointer,uint32_t size) {
    (void)window;(void)size;mock_calls++;mock_submitted=mock_completed=0;mock_reply(pointer,0,0);
    struct halo_metal_reply *r=(void *)(uintptr_t)pointer;
    if(!(flags&HALO_METAL_OFFSCREEN))r->capabilities|=HALO_METAL_CAP_PRESENT_EXACT|HALO_METAL_CAP_PRESENT_SCALED;
    if(mock_mode==1)r->abi_version++;
    if(mock_mode==2)r->capabilities|=UINT32_C(0x80000000);
    if(mock_mode==3)r->capabilities&=~HALO_METAL_CAP_UPLOAD;
    if(mock_mode==4)r->status=HALO_METAL_INVALID;
    if(mock_mode==5)r->reserved=1;
    if(mock_mode==6)r->capabilities|=HALO_METAL_CAP_PRESENT_EXACT;
    if(mock_mode==7)r->submitted_sequence=r->completed_sequence=1;
    return HALO_METAL_OK;
}
int transport_mock_submit(uint32_t packet,uint32_t size,uint32_t pointer,uint32_t reply_size) {
    (void)size;(void)reply_size;mock_calls++;
    const struct halo_metal_packet *h=(void *)(uintptr_t)packet;
    mock_submitted=h->frame_sequence;mock_completed=mock_mode==13?0:h->frame_sequence;mock_reply(pointer,0,0);
    struct halo_metal_reply *r=(void *)(uintptr_t)pointer;
    if(mock_mode==8)r->submitted_sequence=r->completed_sequence=h->frame_sequence+1;
    if(mock_mode==9){r->status=HALO_METAL_INVALID;r->failed_command=1;return HALO_METAL_INVALID;}
    if(mock_mode==10)r->completed_sequence++;
    if(mock_mode==11)r->byte_size=4;
    if(mock_mode==12){r->status=HALO_METAL_GPU_ERROR;return HALO_METAL_GPU_ERROR;}
    if(mock_mode==18){r->status=-99;return -99;}
    return HALO_METAL_OK;
}
int transport_mock_readback(uint32_t id,uint32_t generation,uint32_t plane,uint32_t destination,
                           uint32_t size,uint32_t pointer,uint32_t reply_size) {
    (void)id;(void)generation;(void)plane;(void)destination;(void)reply_size;mock_calls++;
    mock_completed=mock_submitted;mock_reply(pointer,0,size);
    struct halo_metal_reply *r=(void *)(uintptr_t)pointer;
    if(mock_mode==14)r->byte_size++;
    if(mock_mode==15)r->submitted_sequence++;
    if(mock_mode==16){r->status=HALO_METAL_INVALID;r->byte_size=0;r->content_version=1;return HALO_METAL_INVALID;}
    if(mock_mode==17)r->capabilities&=~HALO_METAL_CAP_UPLOAD;
    return HALO_METAL_OK;
}
void transport_mock_shutdown(void){mock_shutdowns++;}

static int mock_start(void) {
    mock_mode=mock_shutdowns=mock_calls=0;
    return mock_guest_setup(&mock_transport,mock_storage,sizeof(mock_storage)) ||
        mock_guest_initialize(&mock_transport,0,HALO_METAL_OFFSCREEN,31);
}
static int mock_packet(void) {
    uint32_t offset;struct halo_metal_command command={HALO_METAL_CLEAR,0};
    return mock_guest_begin(&mock_transport,1) ||
        mock_guest_append_command(&mock_transport,&command,sizeof(command),&offset);
}
int halo_transport_reply_guards(void) {
    for(unsigned int mode=1;mode<=7;mode++) {
        mock_guest_setup(&mock_transport,mock_storage,sizeof(mock_storage));
        mock_mode=mode;mock_shutdowns=0;
        int expected=mode==3?HALO_METAL_UNSUPPORTED:HALO_METAL_INVALID;
        if(mock_guest_initialize(&mock_transport,0,HALO_METAL_OFFSCREEN,31)!=expected ||
           mock_transport.initialized || mock_shutdowns!=1)return 200+(int)mode;
    }
    for(unsigned int mode=8;mode<=12;mode++) {
        if(mock_start() || mock_packet())return 220+(int)mode;
        mock_mode=mode;int expected=mode==12?HALO_METAL_GPU_ERROR:HALO_METAL_INVALID;
        if(mock_guest_submit(&mock_transport)!=expected || !mock_transport.poisoned ||
           mock_guest_begin(&mock_transport,2)!=HALO_METAL_GPU_ERROR)return 240+(int)mode;
        mock_guest_shutdown(&mock_transport);
    }
    if(mock_start() || mock_packet())return 260;
    mock_mode=13;
    if(mock_guest_submit(&mock_transport) || mock_transport.reply.submitted_sequence!=1 ||
       mock_transport.reply.completed_sequence!=0)return 261; /* Do not invent completion. */
    uint32_t word;
    if(mock_guest_readback(&mock_transport,(struct halo_metal_ref){1,1},HALO_METAL_COLOR,&word,4) ||
       mock_transport.reply.completed_sequence!=1)return 262;
    mock_guest_shutdown(&mock_transport);
    for(unsigned int mode=14;mode<=17;mode++) {
        if(mock_start() || mock_packet() || mock_guest_submit(&mock_transport))return 270+(int)mode;
        mock_mode=mode;int expected=mode==17?HALO_METAL_UNSUPPORTED:HALO_METAL_INVALID;
        if(mock_guest_readback(&mock_transport,(struct halo_metal_ref){1,1},HALO_METAL_COLOR,&word,4)!=expected ||
           !mock_transport.poisoned)return 290+(int)mode;
        mock_guest_shutdown(&mock_transport);
    }
    if(mock_start() || mock_packet())return 310;
    mock_mode=18;
    if(mock_guest_submit(&mock_transport)!=HALO_METAL_INVALID || !mock_transport.poisoned)return 311;
    mock_guest_shutdown(&mock_transport);return 0;
}

int halo_transport_alpha_border_guards(void) {
    _Static_assert(sizeof(struct halo_metal_draw_alpha_border)==424,"alpha-border fixed wire record");
    struct halo_metal_draw_alpha_border command;
    zero_bytes(&command,sizeof(command));command.draw.command.opcode=HALO_METAL_DRAW_ALPHA_BORDER;
    command.stage_mask=4;
    const uint32_t malformed_sizes[]={416,423,425,432};
    for(unsigned int i=0;i<4;i++) {
        if(mock_start() || mock_guest_begin(&mock_transport,1))return 320+(int)i;
        unsigned char before[sizeof(mock_storage)];copy_bytes(before,mock_storage,sizeof(before));
        uint32_t offset=UINT32_MAX;
        if(mock_guest_append_command(&mock_transport,&command,malformed_sizes[i],&offset)!=HALO_METAL_INVALID ||
           offset!=UINT32_MAX || mock_transport.size!=24 || mock_transport.command_count ||
           mock_guest_submit(&mock_transport)!=HALO_METAL_INVALID)return 330+(int)i;
        for(unsigned int j=0;j<sizeof(before);j++)if(before[j]!=mock_storage[j])return 340+(int)i;
        mock_guest_shutdown(&mock_transport);
    }
    const uint32_t required[]={HALO_METAL_CAP_ALPHA_BORDER,HALO_METAL_CAP_DRAW};
    for(unsigned int i=0;i<2;i++) {
        if(mock_start() || mock_guest_begin(&mock_transport,1))return 350+(int)i;
        mock_transport.reply.capabilities&=~required[i];uint32_t offset=UINT32_MAX;
        if(mock_guest_append_command(&mock_transport,&command,sizeof(command),&offset)!=HALO_METAL_UNSUPPORTED ||
           offset!=UINT32_MAX || mock_transport.size!=24 || mock_transport.command_count)return 360+(int)i;
        mock_guest_shutdown(&mock_transport);
    }
    if(mock_start() || mock_guest_begin(&mock_transport,1))return 370;
    uint32_t command_offset,payload_offset;unsigned char payload[16];
    for(unsigned int i=0;i<sizeof(payload);i++)payload[i]=(unsigned char)(11+i);
    if(mock_guest_append_command(&mock_transport,&command,sizeof(command),&command_offset) || command_offset!=24 ||
       mock_transport.command_fixed_size!=424 || mock_transport.size!=448 ||
       mock_guest_append_payload(&mock_transport,payload,sizeof(payload),&payload_offset) || payload_offset!=448 ||
       mock_guest_patch_u32(&mock_transport,command_offset,offsetof(struct halo_metal_draw_alpha_border,draw)+
           offsetof(struct halo_metal_draw,vertices_offset),payload_offset))return 371;
    zero_bytes(payload,sizeof(payload));
    const struct halo_metal_draw_alpha_border *stored=(const void *)(mock_storage+command_offset);
    if(stored->draw.command.byte_size!=440 || stored->stage_mask!=4 || stored->reserved ||
       stored->draw.vertices_offset!=448)return 372;
    for(unsigned int i=0;i<sizeof(payload);i++)if(mock_storage[payload_offset+i]!=(unsigned char)(11+i))return 373;
    struct halo_metal_draw legacy;zero_bytes(&legacy,sizeof(legacy));legacy.command.opcode=HALO_METAL_DRAW;
    if(mock_guest_append_command(&mock_transport,&legacy,sizeof(legacy),&command_offset) || command_offset!=464 ||
       mock_transport.command_count!=2 || mock_transport.command_fixed_size!=416 || mock_transport.size!=880)return 374;
    mock_guest_shutdown(&mock_transport);
    mock_mode=0;
    if(mock_guest_setup(&mock_transport,mock_storage,sizeof(mock_storage)) ||
       mock_guest_initialize(&mock_transport,0,HALO_METAL_OFFSCREEN,HALO_METAL_CAP_ALPHA_BORDER))return 375;
    mock_guest_shutdown(&mock_transport);return 0;
}
