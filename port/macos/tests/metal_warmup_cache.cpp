#include "../host/metal_warmup_cache.h"
#include <cassert>
#include <cstdio>

static HaloMetalFunctionKey key(const char *source,bool vertex=true,bool fast=false,bool invariant=true) {
    return {source,vertex,fast,invariant};
}
static HaloMetalWarmupCache fixture() {
    HaloMetalWarmupCache cache;
    assert(cache.learn(key("vertex"))==0 && cache.learn(key("fragment",false))==1);
    assert(cache.learn({0,1,80,260,0x1234,15,1,15,14,5})); return cache;
}
static void resign(std::vector<uint8_t> &bytes) {
    uint64_t sum=halo_metal_source_fingerprint(std::string((const char *)bytes.data(),bytes.size()-8));
    for(unsigned i=0;i<8;i++)bytes[bytes.size()-8+i]=(uint8_t)(sum>>(i*8));
}
int main(int argc,char **argv) {
    assert(argc==2);const std::string test=argv[1];
    if(test=="roundtrip") {
        auto original=fixture();HaloMetalWarmupCache decoded;
        assert(HaloMetalWarmupCache::decode(original.encode(),decoded));
        assert(decoded.encode()==original.encode() && decoded.sourceBytes==14);
        assert(halo_metal_source_fingerprint("hello")==UINT64_C(0xa430d84680aabd0b));
    } else if(test=="contracts") {
        HaloMetalWarmupCache cache;
        for(unsigned flags=0;flags<8;flags++)assert(cache.learn(key("identical",flags&1,flags&2,flags&4))==flags);
        assert(cache.functions.size()==8 && cache.learn(key("identical",true,false,true))==5);
        assert(cache.learn(key("identical\n",true,false,true))==8);
        assert(!cache.learn({0,1,80,260,0,15,0,1,1,1})); // reversed stages
    } else if(test=="bounds") {
        HaloMetalWarmupCache count;
        for(unsigned i=0;i<256;i++)assert(count.learn({std::to_string(i),true,false,true})==i);
        assert(count.learn(key("overflow"))==255 && count.functions.size()==256 && count.functions.front().source=="1");
        HaloMetalWarmupCache size;
        std::string four(4u*1024u*1024u,'v');
        assert(size.learn({four,true,false,true})==0 && size.learn({four,false,false,true})==1);
        assert(size.sourceBytes==size.MaximumSourceBytes && size.learn(key("overflow"))==1 &&
               size.sourceBytes<=size.MaximumSourceBytes);
        HaloMetalWarmupCache oversized;
        assert(oversized.learn({four+"v",true,false,true})==UINT32_MAX);
        assert(oversized.learn(key(""))==UINT32_MAX && oversized.learn({std::string("a\0b",3),true,false,true})==UINT32_MAX);
    } else if(test=="pipelines") {
        auto cache=fixture();auto p=cache.pipelines[0];
        assert(!cache.learn(p));
        for(unsigned i=0;i<1023;i++){p.packed=i;assert(cache.learn(p));}
        assert(cache.pipelines.size()==1024);p.packed=2000;assert(cache.learn(p) && cache.pipelines.size()==1024);
        HaloMetalWarmupCache empty;
        assert(!empty.learn({0,1,80,260,0,15,0,1,1,1}));
    } else if(test=="malformed") {
        auto bytes=fixture().encode();HaloMetalWarmupCache output=fixture();const auto before=output.encode();
        for(size_t length=0;length<bytes.size();length++) {
            std::vector<uint8_t> shortFile(bytes.begin(),bytes.begin()+length);
            assert(!HaloMetalWarmupCache::decode(shortFile,output) && output.encode()==before);
        }
        for(size_t i=0;i<bytes.size();i++) {auto changed=bytes;changed[i]^=128;assert(!HaloMetalWarmupCache::decode(changed,output));}
        auto version=bytes;version[4]=2;resign(version);assert(!HaloMetalWarmupCache::decode(version,output));
        auto count=bytes;count[8]=1;count[9]=1;resign(count);assert(!HaloMetalWarmupCache::decode(count,output));
        auto flags=bytes;flags[20]=8;resign(flags);assert(!HaloMetalWarmupCache::decode(flags,output));
        auto extra=bytes;extra.push_back(0);assert(!HaloMetalWarmupCache::decode(extra,output));
        std::vector<uint8_t> huge(HaloMetalWarmupCache::MaximumFileBytes+1);assert(!HaloMetalWarmupCache::decode(huge,output));
    } else if(test=="state") {
        auto cache=fixture();auto p=cache.pipelines[0];
        p.vertex=1;assert(!cache.learn(p));p=cache.pipelines[0];p.fragment=0;assert(!cache.learn(p));
        p=cache.pipelines[0];p.color=999;assert(!cache.learn(p));p=cache.pipelines[0];p.depth=999;assert(!cache.learn(p));
        p=cache.pipelines[0];p.mask=16;assert(!cache.learn(p));p=cache.pipelines[0];p.blend=2;assert(!cache.learn(p));
        p=cache.pipelines[0];p.source=16;assert(!cache.learn(p));p=cache.pipelines[0];p.operation=6;assert(!cache.learn(p));
        p=cache.pipelines[0];p.color=p.depth=0;assert(!cache.learn(p));p=cache.pipelines[0];p.color=0;assert(!cache.learn(p));
        p.mask=p.blend=0;assert(cache.learn(p));
    } else assert(false);
    std::puts("production warmup cache checks passed");
}
