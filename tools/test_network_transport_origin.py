"""Execute production transport-origin reporting and stock client trust checks.

Socket reads and decoded message handlers are controlled boundaries. The actual
connection reader, origin getter and complete client dispatch function decide
which path and handler may run; no routing or security guard is replaced.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]

PREFIX = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char byte,boolean;
typedef uint16_t word;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define FLAG(bit) (1U<<(bit))
#define TEST_FLAG(value,bit) ((value)&FLAG(bit))
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
#include "bungie_net/common/message_header.h"
#include "networking/network_connection.h"
/* MESSAGE TYPES */
enum {_message_type_error=1,_message_type_data=2,TRANSPORT_ERROR_MESSAGE_TEXT_LENGTH=128};
#define MINIMUM_TRANSPORT_ERROR_MESSAGE_SIZE (sizeof(word)+TRANSPORT_ERROR_MESSAGE_TEXT_LENGTH+sizeof(byte))
#define NETWORK_CLIENT_MESSAGE_HANDLER_FILE "fixture"
struct network_connection {unsigned flags;};
struct transport_address {boolean host;};
struct network_game_client {int unused;};
/* ORIGIN GLOBAL */
static boolean reliable_available,datagram_available;
static unsigned reliable_reads,datagram_reads,distributed_reads,handler_reads[NUMBER_OF_NETWORK_GAME_MESSAGE_TYPES];
static word injected[2];
static boolean network_client_reliable_connection_read(struct network_connection *connection,
    void *buffer,word *size,struct transport_address *address) {
    (void)connection;(void)address;reliable_reads++;
    if(!reliable_available)return FALSE;
    assert(*size>=sizeof(injected));memcpy(buffer,injected,sizeof(injected));*size=sizeof(injected);return TRUE;
}
static boolean network_client_unreliable_connection_read(struct network_connection *connection,
    void *buffer,word *size,struct transport_address *address) {
    (void)connection;(void)address;datagram_reads++;
    if(!datagram_available)return FALSE;
    assert(*size>=sizeof(injected));memcpy(buffer,injected,sizeof(injected));*size=sizeof(injected);return TRUE;
}
static unsigned long system_milliseconds(void) {return 1000;}
static boolean network_game_client_address_matches_server(struct network_game_client *client,
    struct transport_address *address) {(void)client;return address->host;}
static void network_distributed_handle_message(long machine,word const *message,word size) {
    assert(machine==NONE && message && size==sizeof(injected));distributed_reads++;
}
/* MESSAGE HANDLERS */
/* PRODUCTION */
'''

HARNESS = r'''
static void reset(void) {
    reliable_available=datagram_available=FALSE;
    reliable_reads=datagram_reads=distributed_reads=0;
    memset(handler_reads,0,sizeof(handler_reads));
}
static void set_packet(byte kind) {
    memset(injected,0,sizeof(injected));
    injected[0]=(word)((sizeof(injected)<<4)|(_message_type_packet<<2));
    ((byte *)injected)[sizeof(injected)-1]=kind;
}
static void transport_origin(void) {
    struct network_connection connection={FLAG(_connection_create_server_bit)};
    struct transport_address address={TRUE};word buffer[2],size=sizeof(buffer);boolean reliable=TRUE;
    reset();set_packet(_message_server_game_advertise);datagram_available=TRUE;
    assert(network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(!reliable && network_connection_last_read_was_unreliable());
    assert(datagram_reads==1 && !reliable_reads);
    size=sizeof(buffer);datagram_available=FALSE;reliable=TRUE;
    assert(!network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(!reliable && !network_connection_last_read_was_unreliable());
    reset();connection.flags=FLAG(_connection_create_clientside_client_bit);
    reliable_available=datagram_available=TRUE;size=sizeof(buffer);
    assert(network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(reliable && !network_connection_last_read_was_unreliable());
    assert(reliable_reads==1 && !datagram_reads);
    reliable_available=FALSE;size=sizeof(buffer);reliable=TRUE;
    assert(network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(!reliable && network_connection_last_read_was_unreliable());
    datagram_available=FALSE;size=sizeof(buffer);reliable=TRUE;
    assert(!network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(!reliable && !network_connection_last_read_was_unreliable());
    /* The legacy read API shares the same origin flag and NULL-out handling. */
    reliable_available=TRUE;size=sizeof(buffer);
    assert(network_connection_read(&connection,buffer,&size,&address));
    assert(!network_connection_last_read_was_unreliable());
    reliable_available=FALSE;datagram_available=TRUE;size=sizeof(buffer);
    assert(network_connection_read(&connection,buffer,&size,&address));
    assert(network_connection_last_read_was_unreliable());
    connection.flags=FLAG(_connection_create_serverside_client_bit);size=sizeof(buffer);reliable=TRUE;
    unsigned before=datagram_reads;
    assert(!network_connection_read_with_transport(&connection,buffer,&size,&address,&reliable));
    assert(!reliable && !network_connection_last_read_was_unreliable() && datagram_reads==before);
}
static void deliver(byte kind,boolean reliable,boolean server_datagram) {
    struct network_connection connection={FLAG(server_datagram?_connection_create_server_bit:
        _connection_create_clientside_client_bit)};
    struct network_game_client client={0};struct transport_address address={TRUE};
    word buffer[2],size=sizeof(buffer);boolean reported=FALSE;
    set_packet(kind);reliable_available=reliable;datagram_available=!reliable;
    assert(network_connection_read_with_transport(&connection,buffer,&size,&address,&reported));
    assert(reported==reliable);
    assert(network_game_client_handle_message(&client,buffer,(short)size,&address));
}
static void client_trust(void) {
    reset();
    const byte state_messages[]={_message_server_machine_accepted,_message_server_game_settings_update,
        _message_server_begin_game,_message_server_game_update,_message_server_game_over};
    for(unsigned i=0;i<sizeof(state_messages);i++) {
        byte kind=state_messages[i];
        deliver(kind,FALSE,FALSE);assert(!handler_reads[kind]);
        deliver(kind,FALSE,TRUE);assert(!handler_reads[kind]);
        deliver(kind,TRUE,FALSE);assert(handler_reads[kind]==1);
        deliver(kind,FALSE,FALSE);assert(handler_reads[kind]==1); /* No stale reliable classification. */
    }
    const byte discovery[]={_message_server_game_advertise,_message_server_pong};
    for(unsigned i=0;i<sizeof(discovery);i++) {
        byte kind=discovery[i];deliver(kind,FALSE,FALSE);deliver(kind,FALSE,TRUE);deliver(kind,TRUE,FALSE);
        assert(handler_reads[kind]==3);
    }
    /* Distributed host data keeps its separate authenticated-address check. */
    struct network_connection connection={FLAG(_connection_create_clientside_client_bit)};
    struct network_game_client client={0};struct transport_address address={TRUE};
    word buffer[2],size=sizeof(buffer);reliable_available=FALSE;datagram_available=TRUE;
    injected[0]=(word)((sizeof(injected)<<4)|(_message_type_data<<2));
    assert(network_connection_read(&connection,buffer,&size,&address));
    assert(network_game_client_handle_message(&client,buffer,(short)size,&address));assert(distributed_reads==1);
    address.host=FALSE;
    assert(network_game_client_handle_message(&client,buffer,(short)size,&address));assert(distributed_reads==1);
    assert(!network_game_client_handle_message(&client,buffer,2,&address));
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"origin"))transport_origin();
    else if(!strcmp(argv[1],"trust"))client_trust();
    else assert(0);
    return 0;
}
'''


class NetworkTransportOriginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("A native C compiler is required")
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-transport-origin-")
        cls.addClassCleanup(cls.directory.cleanup)
        connection = (ROOT / "source/networking/network_connection.c").read_text()
        handler = block((ROOT / "source/networking/network_client_message_handler.c").read_text(),
                        "boolean network_game_client_handle_message(")
        names = sorted(set(re.findall(r"\b(network_game_client_handle_message_server_\w+)\s*\(", handler)))
        handlers = []
        for name in names:
            kind = name.replace("network_game_client_handle_message_", "_message_")
            handlers.append(f'''static boolean {name}(struct network_game_client *client,word *message,
    short size,struct transport_address *address) {{
    (void)client;(void)message;(void)size;(void)address;handler_reads[{kind}]++;return TRUE;
}}''')
        functions = "\n".join(block(connection, signature) for signature in (
            "boolean network_connection_read_with_transport(", "boolean network_connection_read(\n",
            "boolean network_connection_last_read_was_unreliable("))
        global_flag = re.search(r"static boolean network_connection_last_read_unreliable;", connection)[0]
        enums = block((ROOT / "source/networking/network_messages.h").read_text(),
                      "enum network_game_message_type") + ";"
        source = PREFIX.replace("/* MESSAGE TYPES */", enums).replace("/* ORIGIN GLOBAL */", global_flag)
        source = source.replace("/* MESSAGE HANDLERS */", "\n".join(handlers))
        source = source.replace("/* PRODUCTION */", functions + "\n" + handler) + HARNESS
        # The guest's primitive long has 32 bits. Preserve all control flow.
        source = re.sub(r"\bunsigned long\b", "uint32_t", source)
        source = re.sub(r"\blong\b", "int32_t", source)
        path = Path(cls.directory.name) / "origin.c"
        path.write_text(source)
        cls.executable = path.with_suffix(".exe" if sys.platform == "win32" else "")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
        result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-Wno-sign-compare", *flags,
            "-I", str(ROOT / "source"), str(path), "-o", str(cls.executable)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, case):
        result = subprocess.run([str(self.executable), case], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_read_path_reports_its_transport_and_clears_failure(self):
        self.run_case("origin")

    def test_udp_cannot_dispatch_state_messages_but_discovery_and_host_data_work(self):
        self.run_case("trust")


if __name__ == "__main__":
    unittest.main()
