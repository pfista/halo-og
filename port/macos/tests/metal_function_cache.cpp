/* CPU checks of the production exact-source cache, including retained values
 * and FIFO eviction. Metal compilation/failure behavior is a separate test. */
#include "../host/metal_function_cache.h"
#include <memory>
#include <stdexcept>
#include <cstdio>

static void require(bool condition) { if (!condition) throw std::runtime_error("function cache invariant"); }
static HaloMetalFunctionKey key(std::string source,bool vertex=false,bool fast=false,bool invariant=false) {
    return {std::move(source),vertex,fast,invariant};
}
int main() {
    HaloMetalFunctionCache<unsigned,16,1024> contracts;
    for (unsigned flags=0;flags<8;flags++)
        require(contracts.insert(key("same",flags&1,flags&2,flags&4),flags+1));
    for (unsigned flags=0;flags<8;flags++)
        require(*contracts.find(key("same",flags&1,flags&2,flags&4))==flags+1);
    require(contracts.size()==8 && contracts.sourceBytes()==32);
    require(!contracts.find(key("same ")) && !contracts.find(key("Same")));
    require(!contracts.insert(key("same"),99) && *contracts.find(key("same"))==1);
    require(contracts.insert(key(std::string("same\0",5)),17));
    require(*contracts.find(key(std::string("same\0",5)))==17 && contracts.sourceBytes()==37);

    HaloMetalFunctionCache<unsigned,2,8> bounded;
    require(bounded.insert(key("abc"),1) && bounded.insert(key("de"),2));
    require(bounded.find(key("abc"))); // A hit does not change deterministic FIFO eviction.
    require(bounded.insert(key("f"),3) && !bounded.find(key("abc")));
    require(bounded.size()==2 && bounded.sourceBytes()==3);
    require(!bounded.insert(key("oversized"),4) && bounded.size()==2 && bounded.sourceBytes()==3);
    require(bounded.insert(key("12345678"),5) && bounded.size()==1 && bounded.sourceBytes()==8);
    require(!bounded.find(key("de")) && !bounded.find(key("f")));
    auto moved=std::move(bounded);
    require(moved.find(key("12345678")) && bounded.size()==0 && bounded.sourceBytes()==0);
    require(bounded.insert(key("reuse"),6));
    moved=std::move(bounded);
    require(moved.size()==1 && moved.sourceBytes()==5 && *moved.find(key("reuse"))==6);
    require(bounded.size()==0 && bounded.sourceBytes()==0);
    moved.clear();require(moved.size()==0 && moved.sourceBytes()==0);

    HaloMetalFunctionCache<std::shared_ptr<unsigned>,1,8> ownership;
    auto retained=std::make_shared<unsigned>(42);std::weak_ptr<unsigned> weak=retained;
    require(ownership.insert(key("first"),retained));retained.reset();require(!weak.expired());
    auto program=*ownership.find(key("first"));
    require(ownership.insert(key("next"),std::make_shared<unsigned>(7)) && !weak.expired() && *program==42);
    program.reset();require(weak.expired());
    HaloMetalFunctionCache<unsigned,0,8> disabled;require(!disabled.insert(key("x"),1));
    std::puts("{\"exact_source_and_contracts\":true,\"bounded_fifo\":true,\"retained_values\":true,\"move_and_reset\":true}");
}
