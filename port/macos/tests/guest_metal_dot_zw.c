/* Independent typed raw-D24 depth test. All packets are assembled by the production ILP32
 * C transport. GPU readbacks, never reference images, supply atomic baselines. */
#include "../../linux/src/metal_guest_transport.h"
#include "metal_dot_zw_fixture.h"
#include "../../linux/src/metal_draw_state.c"
_Static_assert(sizeof(void *) == 4, "copy fixture requires actual ILP32");
struct action { uint32_t word[12]; };
extern const struct action halo_dot_actions[HALO_DOT_ACTIONS];
extern const unsigned char halo_dot_inputs[HALO_DOT_INPUT_BYTES];
extern int host_frame_checkpoint(uint32_t, uint32_t, uint32_t, uint32_t);
static unsigned char packet[HALO_DOT_PACKET_CAPACITY] __attribute__((aligned(16)));
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
static uint32_t guest_address(const void *p) { return (uint32_t)(uintptr_t)p; }
static uint32_t fixture_fail(uint32_t index, int status) {
    halo_frame_report[2]=index; halo_frame_report[3]=(uint32_t)status;
    halo_frame_report[4]=transport.reply.failed_command;
    halo_metal_guest_shutdown(&transport); return 100+index;
}
static int bytes_equal(const void *a,const void *b,uint32_t count) {
    const unsigned char *x=a,*y=b;for(uint32_t i=0;i<count;i++) if(x[i]!=y[i]) return 0;return 1;
}
static int typed_guard(uint32_t kind,uint32_t rejection) {
    uint32_t rs[144]={0},ts[4][32]={{0}};
    float c[192][4]={{0}},scale[4]={1,1,16777215,0},offset[4]={0};
    struct metal_draw_state_input in={0};
    in.render_state=rs;in.texture_state=ts;in.constants=c;in.viewport_scale=scale;in.viewport_offset=offset;
    in.viewport[2]=in.viewport[3]=8;in.viewport[5]=1;
    in.target_width=in.target_height=8;in.has_depth=in.sample_count=1;
    in.native_depth_contract=METAL_DRAW_DEPTH_RAW_D24;in.original_auto_depth_format=D3DFMT_D24S8;
    in.depth_surface_format_word=0x2e21;in.floating_point_zbuffer=0;
    rs[D3DRS_PSTEXTUREMODES]=0x54421;rs[D3DRS_PSINPUTTEXTURE]=0x110000;
    rs[D3DRS_PSFINALCOMBINERINPUTSABCD]=4;rs[D3DRS_PSFINALCOMBINERINPUTSEFG]=0x1400;
    rs[D3DRS_SRCBLEND]=D3DBLEND_ONE;rs[D3DRS_DESTBLEND]=D3DBLEND_ZERO;rs[D3DRS_BLENDOP]=D3DBLENDOP_ADD;
    rs[D3DRS_ZENABLE]=rs[D3DRS_ZWRITEENABLE]=1;rs[D3DRS_ZFUNC]=D3DCMP_ALWAYS;
    rs[D3DRS_STENCILFUNC]=D3DCMP_ALWAYS;rs[D3DRS_STENCILFAIL]=rs[D3DRS_STENCILZFAIL]=rs[D3DRS_STENCILPASS]=D3DSTENCILOP_KEEP;
    rs[D3DRS_FRONTFACE]=D3DFRONT_CW;rs[D3DRS_CULLMODE]=D3DCULL_NONE;rs[D3DRS_FILLMODE]=D3DFILL_SOLID;
    rs[D3DRS_COLORWRITEENABLE]=0x01010101;
    for(uint32_t i=0;i<2;i++) {
        in.textures[i]=(struct metal_draw_texture){1,1,1,1,1,0,0,0};
        ts[i][D3DTSS_ADDRESSU]=ts[i][D3DTSS_ADDRESSV]=ts[i][D3DTSS_ADDRESSW]=D3DTADDRESS_CLAMP;
        ts[i][D3DTSS_MINFILTER]=ts[i][D3DTSS_MAGFILTER]=D3DTEXF_POINT;
    }
    switch(kind) {
    case 0:break;
    case 1:in.original_auto_depth_format=D3DFMT_LIN_D24S8;break;
    case 2:in.native_depth_contract=0;break;
    case 3:in.native_depth_contract=2;break;
    case 4:in.has_depth=0;break;
    case 5:in.original_auto_depth_format=D3DFMT_F24S8;break;
    case 6:in.original_auto_depth_format=D3DFMT_D16;break;
    case 7:in.depth_surface_format_word=0x2b21;break;
    case 8:in.floating_point_zbuffer=1;break;
    case 9:in.floating_point_zbuffer=2;break;
    case 10:in.viewport[4]=-.125f;break;
    case 11:in.viewport[5]=1.125f;break;
    case 12:in.viewport[4]=.75f;in.viewport[5]=.25f;break;
    case 13:{uint32_t nan=0x7fc00000;memcpy(&in.viewport[4],&nan,4);break;}
    case 14:scale[2]=1;break;
    case 15:offset[2]=1;break;
    case 16:{uint32_t nan=0x7fc00000;memcpy(&scale[2],&nan,4);break;}
    case 17:in.original_auto_depth_format=0;break;
    case 18:in.depth_surface_format_word=0;break;
    case 19:in.viewport[4]=.25f;in.viewport[5]=.75f;scale[2]=.5f*16777215.0f;offset[2]=.25f*16777215.0f;break;
    default:return -1;
    }
    struct nv2a_pixel_shader_key key,key_before;struct metal_draw_state_output out,out_before;
    struct metal_draw_state_error error;
    memset(&key,0xa5,sizeof(key));memset(&out,0x5a,sizeof(out));memcpy(&key_before,&key,sizeof(key));memcpy(&out_before,&out,sizeof(out));
    struct halo_metal_reply before=transport.reply;
    unsigned char prior[1024];uint32_t size=transport.size,commands=transport.command_count;
    if(size>sizeof(prior))return -1;memcpy(prior,packet,size);
    int status=metal_draw_state_pack(&in,&key,&out,&error);
    if(!bytes_equal(&before,&transport.reply,sizeof(before)) || transport.size!=size || transport.command_count!=commands || !bytes_equal(prior,packet,size)) return -1;
    if(rejection) {
        if(!status || !bytes_equal(&key,&key_before,sizeof(key)) || !bytes_equal(&out,&out_before,sizeof(out))) return -1;
        halo_frame_report[13]++;
    } else {
        if(status || out.depth_contract!=METAL_DRAW_DEPTH_RAW_D24 || out.pixel.depth_scale!=1.0f/16777215.0f ||
           out.pixel.depth_clip_min!=in.viewport[4] || out.pixel.depth_clip_max!=in.viewport[5] || key.texture_modes!=0x54421) return -1;
        halo_frame_report[14]++;
    }
    halo_frame_report[12]++;return 0;
}
uint32_t guest_test(uint32_t unused) {
    (void)unused; halo_frame_report[0]=1; halo_frame_report[1]=1;
    int status=halo_metal_guest_setup(&transport,packet,sizeof(packet));
    if(status) return fixture_fail(0,status);
    status=halo_metal_guest_initialize(&transport,0,HALO_METAL_OFFSCREEN,HALO_DOT_REQUIRED_CAPS);
    if(status) return fixture_fail(0,status);
    for(uint32_t index=0;index<HALO_DOT_ACTIONS;index++) {
        const uint32_t *a=halo_dot_actions[index].word; halo_frame_report[5]=index;
        if(a[0]==1) { /* Begin the next sequence, including after a rejected packet. */
            status=halo_metal_guest_begin(&transport,transport.reply.submitted_sequence+1);
        } else if(a[0]==2) { /* Immutable fixed metadata plus payload descriptors. */
            uint32_t command;
            if(a[1]>HALO_DOT_INPUT_BYTES || a[2]>HALO_DOT_INPUT_BYTES-a[1] ||
               a[3]>HALO_DOT_INPUT_BYTES || a[4]>4 || a[4]*12>HALO_DOT_INPUT_BYTES-a[3]) return fixture_fail(index,-1);
            status=halo_metal_guest_append_command(&transport,halo_dot_inputs+a[1],a[2],&command);
            for(uint32_t p=0;!status && p<a[4];p++) {
                uint32_t d[3],offset; memcpy(d,halo_dot_inputs+a[3]+p*12,sizeof(d));
                if(d[1]>HALO_DOT_INPUT_BYTES || d[2]>HALO_DOT_INPUT_BYTES-d[1]) return fixture_fail(index,-1);
                status=halo_metal_guest_append_payload(&transport,halo_dot_inputs+d[1],d[2],&offset);
                if(!status) status=halo_metal_guest_patch_u32(&transport,command,d[0],offset);
            }
        } else if(a[0]==3) { /* Submit; failed preflight must not commit anything. */
            struct halo_metal_reply before=transport.reply;
            status=halo_metal_guest_submit(&transport);
            if(a[1]) {
                if(status!=(int)a[1] || transport.reply.failed_command!=a[2] ||
                   transport.reply.submitted_sequence!=before.submitted_sequence ||
                   transport.reply.completed_sequence!=before.completed_sequence ||
                   transport.reply.live_resources!=before.live_resources || transport.poisoned) return fixture_fail(index,status?status:-1);
                halo_frame_report[7]++; status=0;
            } else if(!status) halo_frame_report[6]++;
        } else if(a[0]==4) { /* Read/export; optionally save or compare actual baseline. */
            struct halo_metal_ref ref={a[1],a[2]};
            if(a[4]>sizeof(scratch) || a[10]>=6) return fixture_fail(index,-1);
            status=halo_metal_guest_readback(&transport,ref,a[3],scratch,a[4]);
            if(!status && transport.reply.content_version!=a[8]) return fixture_fail(index,-1);
            if(!status && a[9]==1) {
                memcpy(saved[a[10]],scratch,a[4]); saved_sizes[a[10]]=a[4]; saved_versions[a[10]]=transport.reply.content_version;
            } else if(!status && a[9]==2) {
                if(saved_sizes[a[10]]!=a[4] || saved_versions[a[10]]!=transport.reply.content_version) return fixture_fail(index,-1);
                for(uint32_t p=0;p<a[4];p++) if(saved[a[10]][p]!=scratch[p]) return fixture_fail(index,-1);
                halo_frame_report[9]++;
            }
            if(!status) {
                uint32_t metadata[7]={a[1],a[3],a[4],a[1],a[8],a[5],a[6]};
                status=host_frame_checkpoint(a[7],guest_address(metadata),guest_address(scratch),guest_address(&transport.reply));
                if(!status) halo_frame_report[8]++;
            }
        } else if(a[0]==5) { status=typed_guard(a[1],a[2]);
        } else return fixture_fail(index,-1);
        if(status) return fixture_fail(index,status);
    }
    halo_frame_report[10]=(uint32_t)transport.reply.completed_sequence;
    halo_frame_report[11]=transport.reply.live_resources;
    halo_metal_guest_shutdown(&transport); halo_frame_report[1]=4; return 0;
}
