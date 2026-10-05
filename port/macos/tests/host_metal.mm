/* Minimal native runner for the actual ILP32 transport probe. Uses the
 * production guest allocator and import generator; never loads the game. */
#import <Foundation/Foundation.h>
#include <libkern/OSCacheControl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <stdarg.h>
extern "C" {
#include "../host/host.h"
struct host_guest_image host_image;
void *host_sdl_native_metal_layer(uint32_t window) { (void)window; return NULL; }
void host_sdl_native_metal_release(void) {}
int host_linux_errno(int value) { return value; }
void host_logf(int priority,const char *format,...) {
    (void)priority; va_list args; va_start(args,format); vfprintf(stderr,format,args); va_end(args); fputc('\n',stderr);
}
}
struct Elf { uint8_t ident[16]; uint16_t type,machine; uint32_t version;
    uint64_t entry,phoff,shoff; uint32_t flags; uint16_t ehsize,phentsize,phnum,shentsize,shnum,shstrndx; };
struct Segment { uint32_t type,flags; uint64_t offset,vaddr,paddr,filesz,memsz,align; };
static uint32_t (*guest)(uint32_t);
static bool argument_u32(const char *text,uint32_t *value) {
    char *end=nullptr; unsigned long long result=strtoull(text,&end,0);
    if (!text[0] || text[0]=='-' || !end || *end || result>UINT32_MAX) return false;
    *value=(uint32_t)result; return true;
}
static bool image_range(uint32_t address,uint32_t size,uint32_t base,uint32_t span) {
    return address>=base && size<=span && uint64_t(address)-base<=span-size;
}
static bool write_dump(NSString *directory,NSString *name,uint32_t address,uint32_t size) {
    NSData *bytes=[NSData dataWithBytes:guest_pointer(address) length:size];
    return [bytes writeToFile:[directory stringByAppendingPathComponent:name] atomically:YES];
}
static void *run(void *unused) {
    (void)unused; uint32_t result = guest(0);
    printf("{\"kind\":\"native_metal_ilp32_transport\",\"guest_pointer_bits\":32,\"guest_result\":%u,\"passed\":%s}\n",result,result ? "false" : "true");
    return (void *)(uintptr_t)(result ? 1 : 0);
}
int main(int argc,char **argv) { @autoreleasepool {
    // Existing transport probe: image + three import symbols. Draw probe adds
    // mapped span + report/attachment symbols + width/height + evidence folder.
    if (argc != 5 && argc != 6 && argc != 13) return 2;
    NSData *data = [NSData dataWithContentsOfFile:@(argv[1])];
    if (data.length < sizeof(Elf)) return 2; Elf elf; memcpy(&elf,data.bytes,sizeof(elf));
    if (memcmp(elf.ident,"\177ELF\2\1",6) || elf.machine != 183 || elf.phentsize != sizeof(Segment) ||
        elf.phoff > data.length || uint64_t(elf.phnum)*sizeof(Segment) > data.length-elf.phoff) return 2;
    const uint32_t base = 0x88000000u;
    uint32_t requested_span=0x400000u;
    if (argc>=6 && !argument_u32(argv[5],&requested_span)) return 2;
    if (!requested_span || requested_span>0x08000000u) return 2;
    const uint32_t span=(requested_span+HALO_MACOS_PAGE-1)&~(HALO_MACOS_PAGE-1);
    if (host_memory_initialize(base,span)) return 2;
    for (uint32_t i = 0; i < elf.phnum; i++) {
        Segment s; memcpy(&s,(const uint8_t *)data.bytes+elf.phoff+i*sizeof(s),sizeof(s));
        if (s.type != 1) continue;
        if (s.vaddr < base || s.filesz > s.memsz || s.memsz > span || s.vaddr-base > span-s.memsz ||
            s.offset > data.length || s.filesz > data.length-s.offset) return 2;
        memcpy(guest_pointer(s.vaddr),(const uint8_t *)data.bytes+s.offset,s.filesz);
    }
    uint32_t table_address,names_address,count_address;
    if (!argument_u32(argv[2],&table_address) || !argument_u32(argv[3],&names_address) || !argument_u32(argv[4],&count_address) ||
        !image_range(table_address,32,base,span) || !image_range(names_address,1,base,span) || !image_range(count_address,4,base,span)) return 2;
    uint32_t dump[6]={};
    if (argc==13) {
        for (unsigned i=0;i<6;i++) if (!argument_u32(argv[6+i],&dump[i])) return 2;
        uint64_t pixels=uint64_t(dump[4])*dump[5];
        if (!dump[4] || !dump[5] || dump[4]>8192 || dump[5]>8192 || pixels>UINT32_MAX/4 ||
            !image_range(dump[0],64,base,span) || !image_range(dump[1],(uint32_t)pixels*4,base,span) ||
            !image_range(dump[2],(uint32_t)pixels*4,base,span) || !image_range(dump[3],(uint32_t)pixels,base,span)) return 2;
    }
    uint32_t count = *(uint32_t *)guest_pointer(count_address); if (count != 4) return 2;
    uint64_t *table = (uint64_t *)guest_pointer(table_address); const char *name = (const char *)guest_pointer(names_address);
    for (uint32_t i=0;i<count;i++) {
        if (name >= (const char *)guest_pointer(base+span) || !memchr(name,0,(const char *)guest_pointer(base+span)-name)) return 2;
        void *function = host_resolve_import(name); if (!function) return 2;
        table[i]=(uintptr_t)function; name += strlen(name)+1;
    }
    for (uint32_t i=0;i<elf.phnum;i++) {
        Segment s; memcpy(&s,(const uint8_t *)data.bytes+elf.phoff+i*sizeof(s),sizeof(s));
        if (s.type != 1 || !(s.flags & 1)) continue;
        uint64_t start = s.vaddr & ~uint64_t(HALO_MACOS_PAGE-1), end=(s.vaddr+s.memsz+HALO_MACOS_PAGE-1)&~uint64_t(HALO_MACOS_PAGE-1);
        sys_icache_invalidate(guest_pointer(start),end-start);
        if (mprotect(guest_pointer(start),end-start,PROT_READ|PROT_EXEC)) return 2;
    }
    if (elf.entry < base || elf.entry >= base+span) return 2; guest = (uint32_t (*)(uint32_t))guest_pointer(elf.entry);
    void *stack = host_low_map(0x400000,PROT_READ|PROT_WRITE); if (!stack) return 2;
    pthread_attr_t attributes; pthread_attr_init(&attributes); if (pthread_attr_setstack(&attributes,stack,0x400000)) return 2;
    pthread_t thread; if (pthread_create(&thread,&attributes,run,NULL)) return 2; pthread_attr_destroy(&attributes);
    void *result = NULL; if (pthread_join(thread,&result)) return 2;
    if (argc==13) {
        NSString *directory=@(argv[12]); uint32_t bytes=dump[4]*dump[5];
        if (!write_dump(directory,@"guest-report.bin",dump[0],64) ||
            !write_dump(directory,@"native-color-bgra.bin",dump[1],bytes*4) ||
            !write_dump(directory,@"native-depth.bin",dump[2],bytes*4) ||
            !write_dump(directory,@"native-stencil.bin",dump[3],bytes)) return 2;
        uint32_t words[16]; memcpy(words,guest_pointer(dump[0]),sizeof(words));
        const char *keys[]={"abi_version","phase","status","failed_command","completed_sequence_lo","completed_sequence_hi",
            "color_different_bytes","depth_different_bytes","stencil_different_bytes","color_nonclear_pixels",
            "first_color_difference","first_depth_difference","first_stencil_difference","width","height","packet_size"};
        NSMutableDictionary *report=[NSMutableDictionary dictionary];
        for(unsigned i=0;i<16;i++) report[@(keys[i])]=@(words[i]);
        NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
        if (!json || ![json writeToFile:[directory stringByAppendingPathComponent:@"guest-report.json"] atomically:YES]) return 2;
    }
    return (int)(uintptr_t)result;
} }
