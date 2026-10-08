/* Logical packet bounds must survive reuse of a larger backing allocation. */
#include "../host/metal_packet_view.h"
#include <cassert>
#include <cstdio>
#include <limits>

int main() {
    static_assert(std::is_same<decltype(std::declval<const HaloMetalPacketView>().data()),const uint8_t *>::value,
                  "Packet bytes are immutable during validation/execution");
    std::vector<uint8_t> storage(32768,0xa7);
    const uint64_t expected = UINT64_C(0x123456789abcdef0);
    memcpy(storage.data() + 8,&expected,sizeof(expected));
    HaloMetalPacketView packet(storage.data(),16);
    assert(packet.data() == storage.data() && packet.size() == 16);
    uint64_t actual = 0;
    assert(packet.read(8,actual) && actual == expected);
    actual = 42;
    assert(!packet.read(9,actual) && actual == 42);
    assert(!packet.read(16,actual) && actual == 42);
    assert(!packet.read(32760,actual) && actual == 42);
    assert(!packet.contains(std::numeric_limits<size_t>::max(),1));
    assert(!packet.contains(1,std::numeric_limits<size_t>::max()));
    assert(packet.contains(16,0) && !packet.contains(17,0));
    assert(!HaloMetalPacketView(nullptr,16).read(0,actual));
    HaloMetalPacketView whole(storage);
    assert(whole.size() == storage.size() && whole.read(8,actual) && actual == expected);
    puts("production packet logical extent checks passed");
    return 0;
}
