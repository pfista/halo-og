"""Compare wire contracts to independent OpenCE 22 source and exercise gating.

The reference manifest records normalized declarations and compact codec bodies
from cybersecurity/halo-ce-universal 4e8ed2f1, before any OG overlay. It catches
silent packet-layout/enum/codec reversions. The compiled fixture executes the
production capability decoder and admission helpers with both protocol dialects.
Full socket transport and mixed-client gameplay still require runtime tests.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import PREFIX, block, production_code

ROOT = Path(__file__).resolve().parents[1]
COMPILER = shutil.which("clang") or shutil.which("cc")


def normalized(source):
    source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S)
    return "".join(source.split())


def compact_codec_fixture(source, header):
    """Execute the real compact codecs with a fixed 32-bit guest ABI."""
    declarations = [block(header, "struct distributed_vector\n") + ";"]
    for signature in ("enum\n{\n\t/* the player has a unit that is alive */",
                      "enum\n{\n\t/* (alive) camouflaged, and doubly so */",
                      "enum\n{\n\t/* (alive) the vehicle it rides and the seat */",
                      "struct distributed_unit_state\n", "struct distributed_relayed_action\n",
                      "enum\n{\n\t/* a unit state's bytes on the wire:"):
        declarations.append(block(source, signature) + ";")
    functions = [block(source, signature) for signature in (
        "static byte *distributed_put(", "static boolean distributed_take(",
        "static word distributed_unit_state_write(", "static word distributed_unit_state_read(",
        "static word distributed_relayed_action_write(", "static word distributed_relayed_action_read(")]
    fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t byte,boolean;typedef uint16_t word;typedef float real;
typedef struct {real x,y,z;} real_point3d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define NO_PLAYER 255
#define NUMBER_OF_PLAYER_POWERUPS 2
#define DISTRIBUTED_INPUT_HISTORY 4
#define DISTRIBUTED_UNIT_SCALE 32767.f
#define FLAG(bit) (1U<<(bit))
#define TEST_FLAG(value,bit) ((value)&FLAG(bit))
#define SET_FLAG(value,bit,on) ((value)=(on)?((value)|FLAG(bit)):((value)&~FLAG(bit)))
#define csmemcpy memcpy
#define csmemset memset
/* DECLARATIONS */
/* FUNCTIONS */
static void print_wire(const byte *bytes,word size) {
    for(word i=0;i<size;i++)printf("%02x",bytes[i]);puts("");
}
int main(void) {
    byte buffer[128],roundtrip[128];
    for(unsigned mode=0;mode<64;mode++)for(boolean own=0;own<2;own++) {
        struct distributed_unit_state state={0},decoded;
        state.player_index=127;
        SET_FLAG(state.flags,_distributed_unit_alive_bit,mode&1);
        SET_FLAG(state.flags,_distributed_unit_placed_bit,mode&2);
        SET_FLAG(state.flags,_distributed_unit_shield_over_charging_bit,TRUE);
        SET_FLAG(state.flags,_distributed_unit_predicted_bit,TRUE);
        state.killing_player_index=(mode&8)?42:NO_PLAYER;
        state.unit_index=0x12345678;state.vehicle_index=(mode&4)?0x23456789:NONE;
        state.seat_index=-1;state.position=(real_point3d){-1.5f,2.f,4096.f};
        state.velocity=(struct distributed_vector){-32768,32767,0};
        state.forward=(struct distributed_vector){0,0,32767};
        state.up=(struct distributed_vector){0,0,32767};
        if(mode&2)state.up=(struct distributed_vector){-1,2,32766};
        state.predicted_time=(short)0xf123;state.body_vitality=0x4000;state.shield_vitality=0xffff;
        if(mode&8) {
            state.current_body_damage=1;state.recent_body_damage=0x1234;
            state.current_shield_damage=0xabcd;state.recent_shield_damage=0xffff;
        }
        if(mode&16){state.powerup_durations[0]=1;state.powerup_durations[1]=32767;}
        if(mode&32){state.unit_flags=3;state.active_camouflage=255;}
        word size=distributed_unit_state_write(&state,own,buffer);
        assert(size<=DISTRIBUTED_UNIT_STATE_MAXIMUM_SIZE);
        for(word length=0;length<size;length++)assert(!distributed_unit_state_read(buffer,buffer+length,&decoded));
        assert(distributed_unit_state_read(buffer,buffer+size,&decoded)==size);
        assert(distributed_unit_state_write(&decoded,own,roundtrip)==size);
        assert(!memcmp(buffer,roundtrip,size));print_wire(buffer,size);
    }
    for(unsigned history=0;history<8;history++) {
        struct distributed_relayed_action action={0},decoded;
        action.player_index=127;action.desired_weapon_index=-1;action.desired_grenade_index=1;
        action.desired_zoom_level=-1;action.yaw=-32768;action.pitch=32767;
        action.throttle_i=-127;action.throttle_j=127;action.primary_trigger=255;
        action.control_flags[0]=0xf012;
        for(unsigned index=1;index<4;index++)
            action.control_flags[index]=action.control_flags[index-1]^((history&FLAG(index-1))?0x1357:0);
        word size=distributed_relayed_action_write(&action,buffer);
        assert(size<=DISTRIBUTED_RELAYED_ACTION_MAXIMUM_SIZE);
        for(word length=0;length<size;length++)assert(!distributed_relayed_action_read(buffer,buffer+length,&decoded));
        assert(distributed_relayed_action_read(buffer,buffer+size,&decoded)==size);
        assert(distributed_relayed_action_write(&decoded,roundtrip)==size);
        assert(!memcmp(buffer,roundtrip,size));print_wire(buffer,size);
    }
    return 0;
}
'''
    fixture = fixture.replace("/* DECLARATIONS */", "\n".join(declarations))
    fixture = fixture.replace("/* FUNCTIONS */", "\n".join(functions))
    return re.sub(r"\blong\b", "int32_t", fixture)


class OpenCENetworkTests(unittest.TestCase):
    def test_production_unit_and_input_codecs_match_stock_wire_vectors(self):
        reference = json.loads((ROOT / "tools/fixtures/opence_protocol22_wire.json").read_text())
        output = self.compile_and_run(compact_codec_fixture(
            (ROOT / "port/linux/game/network_distributed.c").read_text(),
            (ROOT / "port/linux/game/network_distributed.h").read_text()))
        self.assertEqual(output.splitlines(), reference["compact_wire_vectors"])

    def test_unmodified_upstream_ignores_unsolicited_og_capabilities_in_both_roles(self):
        reference = json.loads((ROOT / "tools/fixtures/opence_protocol22_wire.json").read_text())
        fragments = reference["stock_receive_fragments"]
        declarations, _ = production_code()
        current = (ROOT / "port/linux/game/network_distributed.c").read_text()
        fixture = PREFIX.replace("/* DECLARATIONS */", declarations)
        fixture = fixture.replace("(void)machine; (void)time; assert(0);", "(void)machine; (void)time;")
        functions = "static unsigned vanilla_deliveries; static boolean distributed_handling_stream_message;\n"
        functions += block(current, "static boolean distributed_message_stale(")
        functions += "\n" + fragments["distributed_preamble"]
        functions += "\n" + fragments["distributed_stream_wrapper"]
        functions += r'''
#include "networking/network_performance_protocol.h"
#define GET_MESSAGE_FLAGS(message) ((message)&3)
#define GET_MESSAGE_TYPE(message) (((message)>>2)&3)
#define GET_MESSAGE_SIZE(message) ((message)>>4)
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
enum {_message_type_packet=0,_message_type_data=2,_network_game_server_state_ingame=2,
    _message_server_game_advertise=1,_message_server_pong=2};
static boolean network_connection_last_read_was_unreliable(void) {return FALSE;}
struct network_game_client {int unused;};struct transport_address {int host;};
struct network_game_server {int state;};
struct network_game_server_client_machine {int joined,loaded;};
static boolean network_game_client_address_matches_server(struct network_game_client *client,
    struct transport_address *address) {(void)client;return address->host;}
static int32_t system_milliseconds(void) {return 100;}
static boolean network_game_server_client_machine_is_joined_to_game(struct network_game_server *server,
    struct network_game_server_client_machine *machine) {(void)server;return machine->joined;}
static short network_game_server_get_state(struct network_game_server *server,void *unused) {(void)unused;return server->state;}
static boolean network_game_server_client_machine_is_loaded(struct network_game_server *server,
    struct network_game_server_client_machine *machine) {(void)server;return machine->loaded;}
static void network_game_server_get_client_machine(struct network_game_server *server,
    struct network_game_server_client_machine *machine,int32_t *index) {(void)server;(void)machine;*index=0;}
'''
        functions += fragments["client_data_handler"] + fragments["server_data_handler"]
        functions = re.sub(r"\blong\b", "int32_t", functions).replace("unsigned int32_t", "uint32_t")
        fixture = fixture.replace("/* FUNCTIONS */", functions) + r'''
int main(void) {
    struct network_game_client client={0};struct transport_address address={1};
    struct network_game_server server={0};struct network_game_server_client_machine machine={0};
    word message[8];unsigned capabilities[]={3,7,31,63,127,255,511,1023,2047,4095};
    for(unsigned i=0;i<sizeof(capabilities)/sizeof(capabilities[0]);i++) {
        network_performance_encode((byte *)message,NETWORK_PERFORMANCE_CAPABILITY,capabilities[i]);
        assert(GET_MESSAGE_TYPE(*message)==_message_type_data && GET_MESSAGE_SIZE(*message)==16);
        for(int state=0;state<4;state++)for(int joined=0;joined<2;joined++)for(int loaded=0;loaded<2;loaded++) {
            server.state=state;machine.joined=joined;machine.loaded=loaded;
            connection=_game_connection_network_server;
            assert(upstream_server_handle_message(&server,&machine,message,sizeof(message)));
            assert(!vanilla_deliveries && !distributed_statistics.received);
            connection=_game_connection_network_client;
            assert(upstream_client_handle_message(&client,message,sizeof(message),&address));
            assert(!vanilla_deliveries && !distributed_statistics.received);
        }
    }
    /* An OG host clearing options may send this to a stock client. */
    network_performance_encode((byte *)message,NETWORK_PERFORMANCE_SETTINGS,0);
    connection=_game_connection_network_client;
    assert(upstream_client_handle_message(&client,message,sizeof(message),&address));
    assert(!vanilla_deliveries && !distributed_statistics.received);
    return 0;
}
'''
        self.compile_and_run(fixture)

    def test_extension_frames_obey_existing_receive_time_budget(self):
        source = (ROOT / "source/networking/network_client_manager.c").read_text()
        signature = "static boolean network_game_client_process_messages(\n"
        production = block(source[source.rindex(signature):], signature)
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "networking/network_performance_protocol.h"
typedef unsigned char byte,boolean;typedef unsigned short word;
#define TRUE 1
#define FALSE 0
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define MAXIMUM_NETWORK_MESSAGE_SIZE 4096
#define MAXIMUM_MESSAGE_MILLISECONDS_PER_IDLE 50
#define network_event(...) ((void)0)
enum {_network_game_client_state_pregame=2};
struct game_variant {unsigned flags;};
struct network_game_client {void *connection;int state;struct {struct game_variant variant;} game;};
struct transport_address {int unused;};
static struct game_variant current_variant;
static unsigned reads,mode,handled;
static unsigned long milliseconds;
static boolean network_game_client_cache_settings_pending;
static unsigned long system_milliseconds(void) {return milliseconds;}
static boolean network_connection_read_with_transport(void *connection,word *packet,word *size,
    struct transport_address *address,boolean *reliable) {
    (void)connection;(void)address;assert(*size==4096);
    if(reads==8)return FALSE;
    reads++;milliseconds+=60;*reliable=TRUE;*size=16;
    network_performance_encode((byte *)packet,NETWORK_PERFORMANCE_SETTINGS,0);return TRUE;
}
static boolean network_game_client_receive_performance_capability(const struct network_game_client *client,
    const byte *message,unsigned size,boolean reliable) {(void)client;(void)message;(void)size;(void)reliable;return mode==1;}
static boolean network_game_client_receive_cache_identity(struct network_game_client *client,
    const byte *message,unsigned size,boolean reliable) {(void)client;(void)message;(void)size;(void)reliable;return mode==2;}
static void *global_network_game_server_get(void) {return 0;}
static unsigned network_game_client_performance_settings_flags(const struct network_game_client *client,
    unsigned flags) {(void)client;return flags;}
static struct game_variant *game_engine_get_variant(void) {return &current_variant;}
static void performance_variant_set_flags(struct game_variant *variant,unsigned flags) {variant->flags=flags;handled++;}
static void performance_options_apply_host_flags(unsigned flags) {(void)flags;}
static boolean network_game_client_handle_message(struct network_game_client *client,word *packet,
    word size,struct transport_address *address) {(void)client;(void)packet;(void)size;(void)address;return TRUE;}
/* PRODUCTION */
int main(void) {
    struct network_game_client client={.state=_network_game_client_state_pregame};
    for(mode=1;mode<=3;mode++) {
        reads=milliseconds=handled=0;
        assert(network_game_client_process_messages(&client,TRUE));assert(reads==1);
        if(mode==3)assert(handled==2);
        reads=milliseconds=handled=0;
        assert(network_game_client_process_messages(&client,FALSE));assert(reads==8);
    }
    return 0;
}
'''
        self.compile_and_run(fixture.replace("/* PRODUCTION */", production))
        # The same extracted production loop without the new consumed-frame
        # checks reproduces the formerly unbounded extension path.
        broken = production.replace("\t\t\tif (budgeted && system_milliseconds() - start_time >= MAXIMUM_MESSAGE_MILLISECONDS_PER_IDLE)\n\t\t\t\tbreak;\n\t\t\tcontinue;",
                                    "\t\t\tcontinue;")
        self.assertNotEqual(broken, production)
        self.compile_and_run(fixture.replace("/* PRODUCTION */", broken), expected_success=False)

    def test_production_receiver_enforces_coop_roles_lengths_and_tick_order(self):
        declarations, _ = production_code()
        source = (ROOT / "port/linux/game/network_distributed.c").read_text()
        stale = block(source, "static boolean distributed_message_stale(")
        dispatcher = block(source, "void network_distributed_handle_message(")
        preamble = dispatcher.rsplit("\n\tswitch (header.type)", 1)[0]
        # Endpoint behavior is observable without loading a campaign. Every
        # co-op entry-size adapter has an explicit fixture size; golden source
        # contracts separately preserve the real upstream record declarations.
        fixture = PREFIX.replace("/* DECLARATIONS */", declarations)
        fixture = fixture.replace("(void)machine; (void)time; assert(0);", "(void)machine; (void)time;")
        fixture = re.sub(r"(static word network_(?:actors|coop|objects_damage_animation)[a-z_]*\(void\) \{ )return 0;",
                         r"\1return 8;", fixture)
        functions = "static unsigned deliveries; static byte last_type;\n"
        functions += re.search(r'^static boolean distributed_handling_batch;', source, re.M).group(0) + "\n" + stale + "\n" + preamble
        functions += "\nlast_type=header.type;deliveries++;\n}\n"
        functions = re.sub(r"\blong\b", "int32_t", functions)
        fixture = fixture.replace("/* FUNCTIONS */", functions) + r'''
static void send_fixture(long machine,byte kind,byte count,word size,long tick) {
    word bytes[64]={0};struct distributed_message_header h={0};
    h.type=kind;h.count=count;h.game_time=tick;memcpy(bytes,&h,sizeof(h));
    network_distributed_handle_message(machine,bytes,size);
}
int main(void) {
    memset(distributed_received_times,0xff,sizeof(distributed_received_times));
    connection=_game_connection_network_client;
    byte kinds[]={_distributed_message_actor_states,_distributed_message_coop_presentation,
        _distributed_message_coop_events,_distributed_message_coop_device_groups,
        _distributed_message_coop_object_names,_distributed_message_coop_object_transforms,
        _distributed_message_actor_damage,_distributed_message_coop_object_looks,
        _distributed_message_damage_animations,_distributed_message_coop_screen_effect,
        _distributed_message_coop_device_states};
    for(unsigned i=0;i<sizeof(kinds);i++) {
        unsigned before=deliveries;
        send_fixture(NONE,kinds[i],1,15,10);assert(deliveries==before);
        send_fixture(NONE,kinds[i],1,16,10);assert(deliveries==before+1 && last_type==kinds[i]);
        send_fixture(NONE,kinds[i],1,16,9);assert(deliveries==before+1);
    }
    unsigned before=deliveries;
    send_fixture(NONE,_distributed_message_coop_presentation,0,8,20);
    send_fixture(NONE,_distributed_message_coop_object_names,0,8,20);
    send_fixture(NONE,_distributed_message_coop_skip_vote,1,16,20);
    assert(deliveries==before);
    connection=_game_connection_network_server;
    for(unsigned i=0;i<sizeof(kinds);i++)send_fixture(0,kinds[i],1,16,20);
    assert(deliveries==before);
    send_fixture(0,_distributed_message_coop_skip_vote,0,8,20);assert(deliveries==before);
    send_fixture(0,_distributed_message_coop_skip_vote,1,16,20);assert(deliveries==before+1);
    send_fixture(0,_distributed_message_coop_skip_vote,1,16,19);assert(deliveries==before+1);
    send_fixture(0,78,1,16,20);assert(deliveries==before+1);
    send_fixture(0,0,1,16,20);assert(deliveries==before+1);
    return 0;
}
'''
        self.compile_and_run(fixture)

    def compile_and_run(self, fixture, expected_success=True):
        if not COMPILER:
            self.skipTest("a C11 compiler is required")
        with tempfile.TemporaryDirectory(prefix="halo-opence-wire-") as temporary:
            source = Path(temporary) / "wire.c"
            executable = Path(temporary) / ("wire.exe" if sys.platform == "win32" else "wire")
            source.write_text(fixture)
            flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
            compiled = subprocess.run([COMPILER, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                "-Wno-unused-function", "-Wno-unused-variable", "-I", str(ROOT / "source"),
                "-iquote", str(ROOT / "port/linux/include"), str(source), "-o", str(executable)],
                capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            tested = subprocess.run([str(executable)], capture_output=True, text=True)
            if expected_success:
                self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            else:
                self.assertNotEqual(tested.returncode, 0, "The negative control unexpectedly passed")
            return tested.stdout

    def test_upstream_wire_records_enums_and_compact_codecs_survive_overlay(self):
        reference = json.loads((ROOT / "tools/fixtures/opence_protocol22_wire.json").read_text())
        self.assertEqual(reference["protocol"], 22)
        self.assertEqual(reference["revision"], "4e8ed2f196e0edd1f2830a4de9841686aabbf466")
        for contract in reference["records"]:
            with self.subTest(path=contract["path"], declaration=contract["signature"]):
                production = block((ROOT / contract["path"]).read_text(), contract["signature"])
                self.assertEqual(hashlib.sha256(normalized(production).encode()).hexdigest(),
                                 contract["sha256"])

    def test_stock22_and_extended22_admission_reject_legacy11_capabilities(self):
        weapons = (ROOT / "source/game/weapon_sets.h").read_text()
        capabilities = (ROOT / "source/networking/network_variant_capabilities.h").read_text()
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "halo_port_limits.h"
#include "networking/network_performance_protocol.h"
#include "networking/network_expanded_cache_protocol.h"
struct game_variant { unsigned flags; struct { short weapon_set; } universal_variant; };
enum { _performance_option_fiesta=128 };
static unsigned performance_variant_get_flags(const struct game_variant *variant) {return variant->flags;}
/* WEAPON ENUM */
/* EXPANDED HELPER */
/* REQUIRED HELPER */
int main(void) {
    assert(HALO_PORT_NETWORK_VERSION==22);
    struct game_variant variant={0};
    for (short set=0;set<=13;set++) {
        variant.universal_variant.weapon_set=set;
        assert(network_game_variant_required_capabilities(&variant)==0);
        assert(network_performance_advertised_version(0,22)==22);
    }
    assert(GAME_WEAPON_SET_UNCUT==14 && GAME_WEAPON_SET_ALL==15);
    for (short set=14;set<=15;set++) {
        variant.universal_variant.weapon_set=set;
        unsigned required=network_game_variant_required_capabilities(&variant);
        assert(required==NETWORK_PERFORMANCE_EXPANDED_WEAPONS_CAPABILITY);
        assert(!network_performance_can_join(required,0));
        assert(network_performance_advertised_version(required,22)==0x8016);
    }
    assert(network_performance_version_compatible(22,1,22));
    assert(network_performance_version_compatible(0x8016,5,22));
    assert(!network_performance_version_compatible(0x8016,1,22));
    assert(!network_performance_version_compatible(11,5,22));
    assert(!network_performance_version_compatible(0x800B,5,22));
    assert(!network_performance_version_compatible(20,5,22));
    assert(!network_performance_version_compatible(21,5,22));
    assert(!network_performance_version_compatible(0x8014,5,22));
    assert(!network_performance_version_compatible(0x8015,5,22));
    unsigned char message[16]; unsigned decoded=123;
    network_performance_encode(message,NETWORK_PERFORMANCE_CAPABILITY,4095);
    assert(network_performance_decode(message,16,NETWORK_PERFORMANCE_CAPABILITY,&decoded));
    assert(decoded==4095);
    message[10]='F';message[11]='O';
    decoded=123;
    assert(!network_performance_decode(message,16,NETWORK_PERFORMANCE_CAPABILITY,&decoded));
    assert(decoded==123);
    struct native_map_cache_selection cache={0};
    cache.expanded=1;cache.generation=HALO_EXPANDED_CACHE_GENERATION;
    strcpy(cache.logical_name,"chillout");strcpy(cache.physical_name,"_fiesta_chillout");
    unsigned char offer[NETWORK_EXPANDED_CACHE_MESSAGE_SIZE];
    struct network_expanded_cache_identity identity;
    for (unsigned set=11;set<=15;set++) {
        network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&cache,set);
        assert(network_expanded_cache_decode(offer,sizeof(offer),NETWORK_EXPANDED_CACHE_OFFER,&identity)==(set>=14));
        if(set>=14)assert(identity.weapon_set==set);
    }
    return 0;
}
'''
        fixture = fixture.replace("/* WEAPON ENUM */", block(weapons, "enum\n") + ";")
        fixture = fixture.replace("/* EXPANDED HELPER */", block(weapons,
            "static inline int game_variant_uses_expanded_weapon_set(\n"))
        fixture = fixture.replace("/* REQUIRED HELPER */", block(capabilities,
            "static inline unsigned network_game_variant_required_capabilities(\n"))
        self.compile_and_run(fixture)


if __name__ == "__main__":
    unittest.main()
