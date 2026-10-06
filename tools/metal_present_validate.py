#!/usr/bin/env python3
"""Validate production scaled presentation on an actual native window drawable.

This host wire fixture complements the actual ILP32 clear fixture. Display-sync
property checks do not measure compositor timing or original game frame pacing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <vector>
#include <cmath>
extern "C" {
#include "HOST_HEADER"
struct host_guest_image host_image;
static CAMetalLayer *probe_layer;
void *host_sdl_native_metal_layer(uint32_t window) { return window==1?(__bridge void*)probe_layer:NULL; }
void host_sdl_native_metal_release(void) {}
int host_linux_errno(int value) { return value; }
void host_logf(int priority,const char *format,...) { (void)priority;va_list a;va_start(a,format);vfprintf(stderr,format,a);va_end(a);fputc('\n',stderr); }
}
@interface ProbeLayer : CAMetalLayer
@property(nonatomic,strong) id<CAMetalDrawable> recordedDrawable;
@end
@implementation ProbeLayer
- (id<CAMetalDrawable>)nextDrawable {
    self.recordedDrawable=nil;
    id<CAMetalDrawable> value=[super nextDrawable];self.recordedDrawable=value;return value;
}
@end
#include "BACKEND_SOURCE"
static void require(bool ok,const char *message) { if(!ok){fprintf(stderr,"presentation fixture: %s\n",message);exit(1);} }
static constexpr uint32_t packet_address=0x88001000,reply_address=0x88010000,read_address=0x88011000;
static uint64_t sequence;
static std::vector<uint8_t> packet;
static uint32_t commands;
static halo_metal_reply &response() { return *(halo_metal_reply*)guest_pointer(reply_address); }
static void start() { packet.assign(24,0);commands=0; }
template<class T> static void append(const T &c) { const auto *p=(const uint8_t*)&c;packet.insert(packet.end(),p,p+sizeof(c));commands++; }
static int submit() {
    halo_metal_packet h={HALO_METAL_MAGIC,1,(uint32_t)packet.size(),commands,sequence+1};memcpy(packet.data(),&h,24);
    memcpy(guest_pointer(packet_address),packet.data(),packet.size());
    int status=host_metal_submit(packet_address,(uint32_t)packet.size(),reply_address,sizeof(halo_metal_reply));if(!status)sequence++;return status;
}
static uint8_t component(unsigned x,unsigned y,unsigned k,unsigned width,unsigned height) {
    // Both axes/asymmetric channels and alpha vary; a Y reflection cannot pass.
    unsigned values[4]={20+180*x/(width-1),30+170*y/(height-1),17+(x*41+y*29)%190,45+x*9+y*7};return values[k];
}
static std::vector<uint8_t> source_bytes(unsigned width,unsigned height,unsigned format) {
    std::vector<uint8_t> b(width*height*4);
    for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++)for(unsigned k=0;k<4;k++)
        b[(y*width+x)*4+k]=component(x,y,format==HALO_METAL_BGRA8&&!(k&1)?2-k:k,width,height);
    return b;
}
static void seed(unsigned width,unsigned height,unsigned format) {
    start();halo_metal_create c={{HALO_METAL_CREATE_TEXTURE,sizeof(c)},{1,1},format,width,height,0};append(c);
    auto bytes=source_bytes(width,height,format);uint32_t begin=(uint32_t)packet.size();
    halo_metal_upload u={{HALO_METAL_UPLOAD,(uint32_t)((48+bytes.size()+7)&~7u)},{1,1},0,0,width,height,width*4,begin+48,(uint32_t)bytes.size(),0};
    append(u);packet.insert(packet.end(),bytes.begin(),bytes.end());packet.resize(begin+u.command.byte_size,0);
    require(submit()==0,"source upload failed");
}
static std::vector<uint8_t> drawable_bytes(ProbeLayer *layer) {
    auto texture=layer.recordedDrawable.texture;require(texture!=nil,"real drawable not recorded");
    NSUInteger tight=texture.width*4,row=(tight+255)&~NSUInteger(255);
    auto queue=[layer.device newCommandQueue];auto buffer=[layer.device newBufferWithLength:row*texture.height options:MTLResourceStorageModeShared];
    auto command=[queue commandBuffer];auto blit=[command blitCommandEncoder];
    [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
        sourceSize:MTLSizeMake(texture.width,texture.height,1) toBuffer:buffer destinationOffset:0
        destinationBytesPerRow:row destinationBytesPerImage:row*texture.height];
    [blit endEncoding];[command commit];[command waitUntilCompleted];
    require(command.status==MTLCommandBufferStatusCompleted,"drawable readback failed");
    std::vector<uint8_t> result(tight*texture.height);
    for(NSUInteger y=0;y<texture.height;y++)memcpy(result.data()+y*tight,(const uint8_t*)buffer.contents+y*row,tight);
    return result;
}
static double expected_sample(unsigned x,unsigned y,unsigned channel,unsigned sw,unsigned sh,
    unsigned vx,unsigned vy,unsigned vw,unsigned vh) {
    double tx=(double(x-vx)+.5)/vw*sw-.5,ty=(double(y-vy)+.5)/vh*sh-.5;
    int ix=(int)floor(tx),iy=(int)floor(ty);double fx=tx-ix,fy=ty-iy,v=0;
    for(int dy=0;dy<2;dy++)for(int dx=0;dx<2;dx++) {
        unsigned xx=(unsigned)std::max(0,std::min((int)sw-1,ix+dx)),yy=(unsigned)std::max(0,std::min((int)sh-1,iy+dy));
        v+=component(xx,yy,channel,sw,sh)*(dx?fx:1-fx)*(dy?fy:1-fy);
    }
    return v;
}
int main(int argc,char **argv) { @autoreleasepool {
    require(argc==2,"output directory required");NSString *directory=@(argv[1]);
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    NSWindow *window=[[NSWindow alloc] initWithContentRect:NSMakeRect(160,160,192,128)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    window.title=@"Isolated Metal presentation test";window.contentView.wantsLayer=YES;
    ProbeLayer *layer=[ProbeLayer layer];layer.frame=window.contentView.bounds;layer.contentsScale=1;
    window.contentView.layer=layer;probe_layer=layer;[window orderFront:nil];[NSApp updateWindows];
    require(host_memory_initialize(0x88000000,0x400000)==0,"guest allocator initialization");
    NSMutableArray *rows=[NSMutableArray array];unsigned maximum_error=0,border_pixels=0,linear_pixels=0,atomic_rejections=0,usage_rejections=0;
    const unsigned dimensions[][4]={{4,2,96,80},{4,2,80,24},{3,5,97,81},{3,5,84,140}};
    for(unsigned format=1;format<=2;format++)for(unsigned shape=0;shape<4;shape++) {
        const unsigned *d=dimensions[shape];unsigned sw=d[0],sh=d[1],dw=d[2],dh=d[3];
        layer.drawableSize=CGSizeMake(dw,dh);sequence=0;
        require(host_metal_initialize(1,0,reply_address,sizeof(halo_metal_reply))==0,"window native init failed");
        require((response().capabilities&HALO_METAL_CAP_PRESENT_SCALED)!=0,"scaled presentation capability absent");
        seed(sw,sh,format);
        for(unsigned flags=0;flags<=1;flags++) {
            start();halo_metal_display_settings settings={{HALO_METAL_DISPLAY_SETTINGS,sizeof(settings)},1-flags,0};append(settings);
            require(submit()==0&&layer.displaySyncEnabled==(1-flags!=0),"display setting property not applied");
            start();halo_metal_present_scaled present={{HALO_METAL_PRESENT_SCALED,sizeof(present)},{1,1},flags,0};append(present);
            require(submit()==0&&layer.displaySyncEnabled==(flags!=0),"scaled present/display sync failed");
            require(layer.recordedDrawable.texture.width==dw&&layer.recordedDrawable.texture.height==dh,"drawable dimensions differ");
            auto bytes=drawable_bytes(layer);unsigned vw=dw,vh=dw*sh/sw;if(vh>dh){vh=dh;vw=dh*sw/sh;}
            unsigned vx=(dw-vw)/2,vy=(dh-vh)/2,max_error=0;
            for(unsigned y=0;y<dh;y++)for(unsigned x=0;x<dw;x++) {
                bool inside=x>=vx&&x<vx+vw&&y>=vy&&y<vy+vh;const uint8_t *p=bytes.data()+(y*dw+x)*4;
                require(p[3]==255,"present alpha not opaque");
                if(!inside){require(p[0]==0&&p[1]==0&&p[2]==0,"letterbox not opaque black");border_pixels++;}
                else {linear_pixels++;for(unsigned k=0;k<3;k++){
                    int expected=(int)std::lround(expected_sample(x,y,2-k,sw,sh,vx,vy,vw,vh));
                    unsigned error=(unsigned)std::abs(int(p[k])-expected);max_error=std::max(max_error,error);
                }}
            }
            require(max_error<=1,"top-left/channel/bilinear drawable mismatch");maximum_error=std::max(maximum_error,max_error);
            NSString *name=[NSString stringWithFormat:@"format%u-shape%u-vsync%u.bgra",format,shape,flags];
            require([[NSData dataWithBytes:bytes.data() length:bytes.size()] writeToFile:[directory stringByAppendingPathComponent:name] atomically:YES],"drawable artifact save failed");
            [rows addObject:@{@"format":@(format),@"source_width":@(sw),@"source_height":@(sh),@"width":@(dw),@"height":@(dh),
                @"viewport":@[@(vx),@(vy),@(vw),@(vh)],@"vsync_property":@(layer.displaySyncEnabled),@"max_channel_error":@(max_error),@"file":name}];
            // Invalid later present must preserve the earlier display setting.
            bool before=layer.displaySyncEnabled;uint64_t completed=response().completed_sequence;
            start();settings.display_flags=before?0:1;append(settings);present.display_flags=2;append(present);
            require(submit()==HALO_METAL_UNSUPPORTED&&response().failed_command==1&&response().completed_sequence==completed&&
                layer.displaySyncEnabled==before,"invalid present changed earlier display setting");atomic_rejections++;
            // Presentation must not change source contents or source version.
            require(host_metal_readback(1,1,HALO_METAL_COLOR,read_address,sw*sh*4,reply_address,sizeof(halo_metal_reply))==0,"source readback failed");
            auto source=source_bytes(sw,sh,format);require(response().content_version==1&&memcmp(source.data(),guest_pointer(read_address),source.size())==0,"present altered source target");
        }
        // Render-target-only texture cannot be sampled by scaled presentation.
        // Earlier valid display settings must also remain unapplied on reject.
        start();halo_metal_create_ex render_only={{HALO_METAL_CREATE_TEXTURE_EX,sizeof(render_only)},{2,1},
            format,sw,sh,1,HALO_METAL_TEXTURE_2D,1,HALO_METAL_RENDER_TARGET,0};append(render_only);
        halo_metal_clear initialize={{HALO_METAL_CLEAR,sizeof(initialize)},{2,1},{0,0},HALO_METAL_COLOR,
            0,0,sw,sh,0,{.25,.5,.75,1},1,0};append(initialize);
        require(submit()==0,"render-only target initialization failed");
        bool before=layer.displaySyncEnabled;uint64_t completed=response().completed_sequence;
        start();halo_metal_display_settings settings={{HALO_METAL_DISPLAY_SETTINGS,sizeof(settings)},before?0u:1u,0};append(settings);
        halo_metal_present_scaled invalid_usage={{HALO_METAL_PRESENT_SCALED,sizeof(invalid_usage)},{2,1},0,0};append(invalid_usage);
        require(submit()==HALO_METAL_UNSUPPORTED&&response().failed_command==1&&response().completed_sequence==completed&&
            layer.displaySyncEnabled==before,"scaled present accepted missing ShaderRead usage or changed earlier state");
        usage_rejections++;
        host_metal_shutdown();layer.recordedDrawable=nil;
    }
    [window orderOut:nil];window.contentView.layer=nil;probe_layer=nil;
    NSDictionary *report=@{@"passed":@YES,@"kind":@"native_window_scaled_presentation",@"cases":rows,
        @"max_channel_error":@(maximum_error),@"opaque_black_border_pixels":@(border_pixels),@"bilinear_pixels":@(linear_pixels),
        @"atomic_display_rejections":@(atomic_rejections),@"invalid_texture_usage_rejections":@(usage_rejections),
        @"limits":@[@"One UNORM byte allowance for independent CPU bilinear rounding; original draw/frame strict comparison gates unchanged.",
            @"Actual CAMetalLayer drawable texture checked; compositor timing, refresh pacing and original gameplay presentation timing are not measured.",
            @"Display sync setter property observed; no claim of measured vertical blank synchronization.",@"Native host wire calls use validated guest-address memory; actual ILP32 execution is covered by the separate channel-clear fixture."]};
    NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    require([json writeToFile:[directory stringByAppendingPathComponent:@"window-result.json"] atomically:YES],"result save failed");
    printf("{\"passed\":true,\"cases\":%lu,\"max_channel_error\":%u}\n",(unsigned long)rows.count,maximum_error);
    return 0;
} }
'''


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,default=ROOT)
    p.add_argument('--output',type=Path,default=ROOT/'build/metal-poc/scaled-present-validation')
    p.add_argument('--build-only',action='store_true')
    p.add_argument('--consume-run',type=Path)
    p.add_argument('--consume-returncode',type=int)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.consume_run:
        proof=json.loads((out/'prepared.json').read_text())
        for path,h in proof['source_and_binary_sha256'].items():
            if sha(path)!=h:raise ValueError('Stale presentation proof source/binary: '+path)
        record=json.loads(args.consume_run.read_text())
        if args.consume_returncode!=0 or record.get('passed') is not True:raise ValueError('Actual window presentation failed')
        report=json.loads((out/'native/window-result.json').read_text())
        if len(report['cases'])!=16 or report['atomic_display_rejections']!=16 or report['invalid_texture_usage_rejections']!=8:
            raise ValueError('Incomplete presentation matrix')
        proof.update(complete=True,passed=True,record=record,report=report,returncode=args.consume_returncode,
            artifact_sha256={str(p):sha(p) for p in (out/'native').glob('*') if p.is_file()})
        (out/'result.json').write_text(json.dumps(proof,indent=2)+'\n');print(out/'result.json');return
    if (out/'prepared.json').exists():raise ValueError('Preserve existing proof; use a new output directory')
    root=args.source_root.resolve();snapshot=out/'source-snapshot';sources={}
    names=['port/macos/host/host.h','port/macos/host/host_memory.c','port/macos/host/host_metal.mm',
        'port/macos/host/metal_function_cache.h','port/macos/host/metal_draw_encoder.h','port/macos/host/metal_draw_encoder.mm',
        'port/macos/include/halo_metal_abi.h','port/android/include/halo_android_abi.h']
    for name in names:
        src=root/name;dst=snapshot/name;dst.parent.mkdir(parents=True,exist_ok=True);h=sha(src);shutil.copy2(src,dst)
        if sha(src)!=h or sha(dst)!=h:raise ValueError('Presentation source changed during snapshot')
        sources[str(src)]=h;sources[str(dst)]=h
    sources[str(Path(__file__).resolve())]=sha(__file__)
    source=out/'window-probe.mm';source.write_text(HARNESS.replace('HOST_HEADER',str(snapshot/'port/macos/host/host.h'))
        .replace('BACKEND_SOURCE',str(snapshot/'port/macos/host/host_metal.mm')))
    flags=['-arch','arm64','-mmacosx-version-min=14.0','-O2','-g','-DHALO_MACOS=1',
        '-I'+str(snapshot/'port/macos/host'),'-I'+str(snapshot/'port/android/include')]
    objects=[]
    # Reuse the four-import generated resolver from the independent clear probe.
    table=ROOT/'build/metal-poc/channel-clear-validation/host_import_table.c'
    for i,src in enumerate([snapshot/'port/macos/host/host_memory.c',table,snapshot/'port/macos/host/metal_draw_encoder.mm',source]):
        obj=out/f'{i}.o';cpp=src.suffix=='.mm'
        command=['clang++' if cpp else 'clang',*flags,*(['-std=c++17','-fobjc-arc','-fblocks'] if cpp else []),
            *(['-Wall','-Wextra','-Werror'] if src==source else []),'-c',src,'-o',obj]
        subprocess.run(command,cwd=ROOT,check=True);objects.append(obj);sources[str(src)]=sha(src)
    executable=out/'window-probe'
    subprocess.run(['clang++',*flags,*objects,'-framework','AppKit','-framework','Foundation','-framework','Metal',
        '-framework','QuartzCore','-o',executable],cwd=ROOT,check=True)
    for path,h in sources.items():
        if sha(path)!=h:raise ValueError('Source changed during presentation build')
    native=out/'native';native.mkdir();command=[str(executable),str(native)]
    sources[str(executable)]=sha(executable)
    proof=dict(kind='native_metal_scaled_present_proof',schema_version=1,complete=False,passed=False,
        source_and_binary_sha256=sources,execution_command=command,
        scope='Production host backend, real NSWindow/CAMetalLayer, actual recorded drawable GPU bytes; native host wire fixture.')
    (out/'prepared.json').write_text(json.dumps(proof,indent=2)+'\n')
    if args.build_only:print(json.dumps(dict(prepared=str(out/'prepared.json'),execution_command=command),indent=2));return
    result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
    (native/'stdout.json').write_text(result.stdout);(native/'stderr.log').write_text(result.stderr)
    if result.returncode:raise SystemExit('Presentation failed; diagnostics retained')
    subprocess.run([sys.executable,__file__,'--output',out,'--consume-run',native/'stdout.json',
        '--consume-returncode',str(result.returncode)],check=True)


if __name__=='__main__':main()
