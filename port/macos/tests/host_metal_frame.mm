/* Diagnostic ELF loader/checkpoint writer, using the production import path.
 * No renderer or expected attachment bytes live in this driver. */
#import <Foundation/Foundation.h>
#include <libkern/OSCacheControl.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <stdarg.h>
extern "C" {
#include "../host/host.h"
#include "../include/halo_metal_abi.h"
struct host_guest_image host_image;
void *host_sdl_native_metal_layer(uint32_t window) { (void)window;return NULL; }
void host_sdl_native_metal_release(void) {}
int host_linux_errno(int value) { return value; }
void host_logf(int priority,const char *format,...) {
    (void)priority;va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);fputc('\n',stderr);
}
}
struct Elf { uint8_t ident[16];uint16_t type,machine;uint32_t version;uint64_t entry,phoff,shoff;
    uint32_t flags;uint16_t ehsize,phentsize,phnum,shentsize,shnum,shstrndx; };
struct Segment { uint32_t type,flags;uint64_t offset,vaddr,paddr,filesz,memsz,align; };
struct Readback { uint32_t resource,plane,bytes,target_id,version,width,height; };
static uint32_t (*guest)(uint32_t);
static NSString *output_directory;
static NSMutableArray *checkpoint_records;
static bool argument(const char *text,uint32_t *value) {
    char *end=nullptr;unsigned long long result=strtoull(text,&end,0);
    if(!text[0] || text[0]=='-' || !end || *end || result>UINT32_MAX)return false;
    *value=(uint32_t)result;return true;
}
static bool copy_guest(uint32_t address,void *destination,uint32_t bytes) {
    if(!address || !bytes || uint64_t(address)+bytes>UINT64_C(0x100000000) || !host_low_owns((uintptr_t)guest_pointer(address),bytes))return false;
    mach_vm_size_t copied=0;
    return mach_vm_read_overwrite(mach_task_self(),(mach_vm_address_t)guest_pointer(address),bytes,
        (mach_vm_address_t)destination,&copied)==KERN_SUCCESS && copied==bytes;
}
extern "C" int host_frame_checkpoint(uint32_t event,uint32_t metadata,uint32_t data,uint32_t reply_address) {
    @autoreleasepool {
        Readback r;halo_metal_reply reply;
        if(!copy_guest(metadata,&r,sizeof(r)) || !copy_guest(reply_address,&reply,sizeof(reply)) ||
            !r.target_id || r.resource!=r.target_id || !r.width || !r.height || r.width>8192 || r.height>8192 ||
            (r.plane!=1 && r.plane!=2 && r.plane!=4 && r.plane!=8) ||
            (r.plane==8 ? (r.width!=1 || r.height!=1 || r.bytes!=8) :
                uint64_t(r.width)*r.height*(r.plane==4?1u:4u)!=r.bytes) ||
            (event!=UINT32_MAX && event>65535) || reply.abi_version!=1 || reply.status!=HALO_METAL_OK)return HALO_METAL_INVALID;
        NSMutableData *bytes=[NSMutableData dataWithLength:r.bytes];
        if(!bytes || !copy_guest(data,bytes.mutableBytes,r.bytes))return HALO_METAL_MEMORY;
        NSString *name=[NSString stringWithFormat:@"event-%u-target-%u-version-%u-plane-%u.bin",event,r.target_id,r.version,r.plane];
        NSString *path=[output_directory stringByAppendingPathComponent:name];
        if([[NSFileManager defaultManager] fileExistsAtPath:path] || ![bytes writeToFile:path atomically:YES])return HALO_METAL_MEMORY;
        [checkpoint_records addObject:@{@"event":@(event),@"target_id":@(r.target_id),@"version":@(r.version),
            @"plane":@(r.plane),@"width":@(r.width),@"height":@(r.height),@"bytes":@(r.bytes),@"file":name,
            @"wire_content_version":@(reply.content_version),@"completed_sequence":@(reply.completed_sequence)}];
        return HALO_METAL_OK;
    }
}
static void *run(void *unused) {
    (void)unused;uint32_t result=guest(0);
    printf("{\"kind\":\"native_metal_ilp32_ordered_frame\",\"guest_pointer_bits\":32,\"guest_result\":%u,\"transport_passed\":%s}\n",result,result?"false":"true");
    return (void *)(uintptr_t)(result?1:0);
}
int main(int argc,char **argv) { @autoreleasepool {
    if(argc!=8)return 2;
    uint32_t table_address,names_address,count_address,span,report_address;
    if(!argument(argv[2],&table_address) || !argument(argv[3],&names_address) || !argument(argv[4],&count_address) ||
        !argument(argv[5],&span) || !argument(argv[6],&report_address) || !span || span>0x20000000u)return 2;
    output_directory=@(argv[7]);checkpoint_records=[NSMutableArray new];
    BOOL directory=NO;
    if(![[NSFileManager defaultManager] fileExistsAtPath:output_directory isDirectory:&directory] || !directory)return 2;
    NSData *data=[NSData dataWithContentsOfFile:@(argv[1])];
    if(data.length<sizeof(Elf))return 2;Elf elf;memcpy(&elf,data.bytes,sizeof(elf));
    if(memcmp(elf.ident,"\177ELF\2\1",6) || elf.machine!=183 || elf.phentsize!=sizeof(Segment) ||
        elf.phoff>data.length || uint64_t(elf.phnum)*sizeof(Segment)>data.length-elf.phoff)return 2;
    const uint32_t base=0x88000000u;span=(span+HALO_MACOS_PAGE-1)&~(HALO_MACOS_PAGE-1);
    if(host_memory_initialize(base,span))return 2;
    for(uint32_t i=0;i<elf.phnum;i++) {
        Segment s;memcpy(&s,(const uint8_t *)data.bytes+elf.phoff+i*sizeof(s),sizeof(s));
        if(s.type!=1)continue;
        if(s.vaddr<base || s.filesz>s.memsz || s.memsz>span || s.vaddr-base>span-s.memsz ||
            s.offset>data.length || s.filesz>data.length-s.offset)return 2;
        memcpy(guest_pointer(s.vaddr),(const uint8_t *)data.bytes+s.offset,s.filesz);
    }
    uint32_t count;
    if(!copy_guest(count_address,&count,4) || count!=5 || !host_low_owns((uintptr_t)guest_pointer(table_address),count*8))return 2;
    uint64_t *table=(uint64_t *)guest_pointer(table_address);uint32_t name_address=names_address;
    for(uint32_t i=0;i<count;i++) {
        char name[256];unsigned n=0;
        for(;n<sizeof(name);n++) {
            if(!copy_guest(name_address+n,&name[n],1))return 2;
            if(!name[n])break;
        }
        if(n==sizeof(name))return 2;
        void *function=host_resolve_import(name);if(!function)return 2;
        table[i]=(uintptr_t)function;name_address+=n+1;
    }
    for(uint32_t i=0;i<elf.phnum;i++) {
        Segment s;memcpy(&s,(const uint8_t *)data.bytes+elf.phoff+i*sizeof(s),sizeof(s));
        if(s.type!=1 || !(s.flags&1))continue;
        uint64_t start=s.vaddr&~uint64_t(HALO_MACOS_PAGE-1),end=(s.vaddr+s.memsz+HALO_MACOS_PAGE-1)&~uint64_t(HALO_MACOS_PAGE-1);
        sys_icache_invalidate(guest_pointer(start),end-start);
        if(mprotect(guest_pointer(start),end-start,PROT_READ|PROT_EXEC))return 2;
    }
    if(elf.entry<base || elf.entry>=base+span)return 2;guest=(uint32_t (*)(uint32_t))guest_pointer(elf.entry);
    void *stack=host_low_map(0x400000,PROT_READ|PROT_WRITE);if(!stack)return 2;
    pthread_attr_t attributes;pthread_attr_init(&attributes);
    if(pthread_attr_setstack(&attributes,stack,0x400000))return 2;
    pthread_t thread;if(pthread_create(&thread,&attributes,run,NULL))return 2;pthread_attr_destroy(&attributes);
    void *result=NULL;if(pthread_join(thread,&result))return 2;
    uint32_t report[16];if(!copy_guest(report_address,report,sizeof(report)))return 2;
    NSMutableArray *words=[NSMutableArray new];for(unsigned i=0;i<16;i++)[words addObject:@(report[i])];
    NSData *json=[NSJSONSerialization dataWithJSONObject:@{@"report":words,@"checkpoints":checkpoint_records} options:NSJSONWritingPrettyPrinted error:nil];
    if(!json || ![json writeToFile:[output_directory stringByAppendingPathComponent:@"checkpoints.json"] atomically:YES])return 2;
    return (int)(uintptr_t)result;
} }
