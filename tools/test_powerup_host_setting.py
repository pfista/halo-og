"""Exercise host-owned powerup sessions and compatibility without real transport."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]


def run_fixture(text, production=()):
    with tempfile.TemporaryDirectory(prefix="halo-powerup-host-setting-") as temporary:
        directory = Path(temporary)
        source = directory / "fixture.c"
        source.write_text(text)
        # The session module only needs the primitive game boolean/config API.
        (directory / "cseries.h").write_text("typedef int boolean;\n#define TRUE 1\n#define FALSE 0\n")
        (directory / "port_config.h").write_text("int config_boolean(char const *name);\n")
        binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
        subprocess.run(["clang", "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-function", "-I", str(directory), "-I", str(ROOT / "source"),
                        str(source), *(str(path) for path in production), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


def network_fixture_source():
    """Use the real serializers, receiver, loaded barrier and connection state.

    Transport queues contain complete messages, as the reliable connection does.
    Only unrelated game/cache/clock operations are replaced by narrow stubs.
    The host latch is a separate simulated machine; the client uses the actual
    session module so an opposite local configuration cannot drive its policy.
    """
    manager = (ROOT / "source/networking/network_server_manager.c").read_text()
    sender = (ROOT / "source/networking/network_server_message_handler.c").read_text()
    client = (ROOT / "source/networking/network_client_manager.c").read_text()
    sender = sender[sender.index("/* ---------- public code */"):]
    client = client[client.index("/* ---------- public code */"):]
    required = (ROOT / "source/networking/network_variant_capabilities.h").read_text()
    host_functions = "\n".join(block(manager, signature) for signature in (
        "void network_game_server_performance_capability(\n",
        "boolean network_game_server_performance_supported(\n",
        "boolean network_game_server_powerup_sync_acknowledge(\n",
        "boolean network_game_server_powerup_sync_ready(\n",
    ))
    host_functions += "\n" + block(required, "static inline unsigned network_game_host_required_capabilities(\n")
    host_functions += "\n" + "\n".join(block(sender, signature) for signature in (
        "static boolean network_game_server_send_performance_capability(\n",
        "static boolean network_game_server_send_powerup_sync_settings(\n",
        "boolean network_game_server_send_game_settings_to_client_machine(\n",
        "boolean network_game_server_send_game_settings_to_all_machines(\n",
        "static boolean network_game_server_handle_message_client_loaded(\n",
    ))
    # The C fixture contains both sides. This substitution names only the host
    # machine's already-latched value; the receiver links the real client API.
    host_functions = host_functions.replace("network_powerup_sync_host_enabled()", "fixture_host_enabled()")
    client_functions = "\n".join(block(client, signature) for signature in (
        "static boolean network_game_client_receive_performance_capability(\n",
        "static boolean network_game_client_send_powerup_sync_ack(struct network_game_client *client)",
        "static boolean network_game_client_process_incoming_messages(\n",
        "boolean network_game_client_game_has_started(\n",
        "void network_game_client_reset(\n",
        "void network_game_client_dispose(\n",
    ))
    admission = block(sender, "if (!network_game_server_performance_supported(server_client_machine,\n")
    ack_receive = block(sender, "if (network_game_server_client_machine_is_joined_to_game(server, machine) &&\n\t\t\t\t\tnetwork_performance_powerup_sync_decode")
    # These assignments occur in the actual remove and accept-connection paths.
    reset_signature = "network_game_server_performance_capabilities[i] = 0;"
    remove = block(manager, "boolean network_game_server_remove_client_machine_from_game(\n")
    accept_start = manager.index(reset_signature, manager.index("new_connection;", manager.index("boolean network_game_server_remove_client_machine_from_game(\n")))
    remove_start = remove.index(reset_signature)
    remove_reset = remove[remove_start:remove.index("server->client_machines[i].last_heard_time", remove_start)]
    accept_reset = manager[accept_start:manager.index("network_game_invalidate_machine", accept_start)]
    create = block(manager, "struct network_game_server *network_game_server_create(\n")
    begin = create[create.index("csmemset(server, 0, sizeof(*server));"):create.index("if (server != NULL)")]
    dispose = block(manager[manager.index("/* ---------- public code */"):], "void network_game_server_dispose(\n")
    end_start = dispose.index("network_powerup_sync_host_end();")
    end = dispose[end_start:dispose.index("p2p_set_game_player_counts", end_start)]
    return NETWORK_FIXTURE.replace("/* HOST FUNCTIONS */", host_functions).replace(
        "/* CLIENT FUNCTIONS */", client_functions).replace("/* ADMISSION */", admission).replace(
        "/* ACK RECEIVE */", ack_receive).replace("/* REMOVE RESET */", remove_reset).replace(
        "/* ACCEPT RESET */", accept_reset).replace("/* HOST BEGIN */", begin).replace("/* HOST END */", end)


NETWORK_FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "networking/network_performance_protocol.h"
#include "networking/network_powerup_sync.h"
typedef int boolean;
typedef unsigned char byte;
typedef unsigned short word;
typedef word message_header;
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define MAXIMUM_NETWORK_MACHINE_COUNT 3
#define MAXIMUM_NUMBER_OF_PLAYERS 1
#define MAXIMUM_NETWORK_MESSAGE_SIZE 64
#define NETWORK_GAME_MESSAGE_VERSION 11
#define VALID_INDEX(i,n) ((i)>=0 && (i)<(n))
#define MIN(a,b) ((a)<(b) ? (a):(b))
#define csmemset memset
#define csmemcpy memcpy
#define SET_FLAG(f,b,v) ((f)=(v) ? (f)|(1u<<(b)):(f)&~(1u<<(b)))
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
#define GET_MESSAGE_SIZE(m) 2
#define TICKS_PER_SECOND 30
enum { _network_game_server_state_pregame=1,_network_game_server_state_ingame=2,_network_game_server_state_postgame=3,
    _network_game_client_state_searching=0,_network_game_client_state_joining=1,_network_game_client_state_pregame=2,
    _network_game_client_state_ingame=3,_network_game_client_connection_established_bit=0,
    _network_game_client_join_request_sent_bit=1,_network_game_client_error_unknown=1,_network_game_client_error_none=0,
    _message_server_game_settings_update=1,_message_client_loaded=2,_message_server_machine_rejected=3,
    _rejection_code_version_too_old=1,_network_game_packet_class_client_ingame=1,_game_connection_network_client=1,
    _performance_option_input_delay=32,_performance_option_hardcore=64,_performance_option_fiesta=128,_performance_option_hardcore_camo=256 };
struct game_variant { unsigned flags;struct { int weapon_set; } universal_variant; };
struct network_player { int machine_index,controller_index,player_list_index; };
struct network_game { struct game_variant variant;struct network_player players[1]; };
struct network_game_server_client_machine { int machine_index,joined,local,late,loaded; };
struct network_game_server { struct network_game game;int state;struct network_game_server_client_machine machines[3]; };
struct network_game_client { void *connection;int state,machine_index,next_update_number,connection_silent,seconds_to_game_start;
    int flags,error,join_in_progress,last_broadcast_search_time;struct network_game game; };
struct transport_address { int unused; };
struct message_server_game_settings_update { word total_size,offset,length,pad;byte data[8]; };
struct message_client_loaded { int unused; };
struct message_server_machine_rejected { int code; };
struct cache_selection { int unused; };
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
static struct { unsigned weapon_set;struct cache_selection selection; } network_game_client_cache_offer;
static boolean network_game_client_cache_offer_valid,network_game_client_cache_settings_pending,network_game_client_cache_begin_pending;
#endif
static unsigned network_game_client_performance_host_capabilities;
static long network_game_client_late_join_time;
static int network_game_client_late_join_clock_pending,network_game_client_incompatibility_told,network_game_client_add_player_requested[1];
static int network_game_client_dont_use_directly_in_use;
static word network_game_server_performance_capabilities[3];
static boolean network_game_server_powerup_sync_acknowledged[3];
static boolean network_game_settings_update_pending;
static unsigned long network_game_settings_update_time;
static struct network_game_server server,*local_server;
static struct game_variant runtime_variant;
static int preference,host_enabled,remote_supported,reads,settings_pieces,acks,loaded_writes,ordinary_settings_writes,rejections;
static int normal_loaded,late_loaded,object_requests,local_objects,ignored_controls,ack_write_success=1;
struct packet { byte bytes[64];word size;int reliable; };
static struct packet queues[3][16];static int queue_count[3],queue_next;
int config_boolean(char const *name) { assert(!strcmp(name,"network.experimental_powerup_sync"));reads++;return preference; }
int config_write_boolean(char const *name,int value) { (void)name;(void)value;assert(0);return 0; }
static int fixture_host_enabled(void) { return host_enabled; }
static int halo_performance_audio_available(void) { return 0; }
static unsigned network_game_variant_required_capabilities(struct game_variant const *v) { return v->flags; }
static struct network_game_server *global_network_game_server_get(void) { return local_server; }
static struct game_variant *game_engine_get_variant(void) { return &runtime_variant; }
static unsigned network_game_client_performance_settings_flags(struct network_game_client const *c,unsigned f) { (void)c;return f; }
static void performance_variant_set_flags(struct game_variant *v,unsigned f) { v->flags=f;ordinary_settings_writes++; }
static void performance_options_apply_host_flags(unsigned f) { (void)f; }
static unsigned long system_milliseconds(void) { return 100; }
static int network_game_server_client_machine_is_local(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;return m->local; }
static int network_game_server_client_machine_is_joined_to_game(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;return m->joined; }
static int network_game_server_machine_is_loading_late(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;return m->late; }
static struct network_game_server_client_machine *network_game_server_get_client_machine_at_index(struct network_game_server *s,int i) { return &s->machines[i]; }
static struct network_game *network_game_server_get_game(struct network_game_server *s) { return &s->game; }
static int network_game_server_get_state(struct network_game_server *s,void *unused) { (void)unused;return s->state; }
static int network_game_server_client_machine_is_loaded(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;return m->loaded; }
static void network_game_server_client_machine_game_loading_complete(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;m->loaded=1;normal_loaded++;object_requests++; }
static void network_game_server_late_joiner_loaded(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;m->loaded=1;late_loaded++;object_requests++; }
static int network_game_server_send_cache_identity(struct network_game_server *s,struct network_game_server_client_machine *m,void const *g) { (void)s;(void)m;(void)g;return TRUE; }
static int network_game_server_client_machine_has_cache_identity(struct network_game_server *s,struct network_game_server_client_machine *m) { (void)s;(void)m;return TRUE; }
static int network_game_client_receive_cache_identity(struct network_game_client *c,byte const *p,unsigned n,int r) { (void)c;(void)p;(void)n;(void)r;return FALSE; }
static int native_map_cache_uses_global_arsenal(struct game_variant const *v) { (void)v;return FALSE; }
static int network_game_client_defer_cache_begin(void) { return FALSE; }
static struct cache_selection *native_map_cache_current(void) { static struct cache_selection v;return &v; }
static int native_map_cache_selection_equal(struct cache_selection const *a,struct cache_selection const *b) { (void)a;(void)b;return TRUE; }
static int network_game_client_send_cache_ready(struct network_game_client *c) { (void)c;return TRUE; }
static void *create_network_game_message(unsigned kind,void const *data,unsigned size) {
    static byte encoded[64];memset(encoded,0,sizeof(encoded));encoded[0]=(byte)kind;
    assert(size<sizeof(encoded)-2);memcpy(encoded+2,data,size);return encoded;
}
static int network_game_server_send_message_to_client_machine(struct network_game_server *s,struct network_game_server_client_machine *m,void const *message) {
    (void)s;int index=m->machine_index;assert(queue_count[index]<16);
    struct packet *packet=&queues[index][queue_count[index]++];
    packet->size=((byte const *)message)[0]==8 ? 16:sizeof(struct message_server_game_settings_update)+2;
    if(((byte const *)message)[0]==_message_server_machine_rejected) { rejections++;packet->size=6; }
    memcpy(packet->bytes,message,packet->size);packet->reliable=TRUE;return TRUE;
}
static int network_game_server_send_message_to_all_machines(struct network_game_server *s,void *message) {
    for(int i=0;i<3;i++) if(s->machines[i].joined && !s->machines[i].late)
        assert(network_game_server_send_message_to_client_machine(s,&s->machines[i],message));
    return TRUE;
}
static int network_connection_read_with_transport(void *connection,word *message,word *size,struct transport_address *address,boolean *reliable) {
    (void)connection;(void)address;if(queue_next==queue_count[1]) return FALSE;
    struct packet *packet=&queues[1][queue_next++];assert(*size>=packet->size);
    memcpy(message,packet->bytes,packet->size);*size=packet->size;*reliable=packet->reliable;return TRUE;
}
static int network_game_client_handle_message(struct network_game_client *c,word *p,word size,struct transport_address *address) {
    (void)c;(void)address;
    if(((byte const *)p)[0]==8) { ignored_controls++;return TRUE; }
    assert(((byte const *)p)[0]==_message_server_game_settings_update && size>=2);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    if(remote_supported) assert(network_powerup_sync_client_confirmed() && network_powerup_sync_effective()==host_enabled);
#endif
    assert(network_powerup_sync_effective()==host_enabled);settings_pieces++;return TRUE;
}
static int decode_network_game_message(void *out,word *p,short *size,short *type,short *version,int packetclass) {
    (void)out;(void)p;(void)size;(void)type;(void)version;(void)packetclass;return TRUE;
}
static boolean network_game_server_handle_message_client_loaded(struct network_game_server *,struct network_game_server_client_machine *,word *,short);
static boolean network_game_server_powerup_sync_acknowledge(struct network_game_server_client_machine *,int);
static int receive_ack(struct network_game_server *server,struct network_game_server_client_machine *machine,word *message,unsigned message_buffer_size);
static int network_game_client_write(void *connection,void *packet,unsigned size,void *address,int reliable) {
    (void)connection;assert(!address && reliable==1);
    int enabled=-1;
    if(network_performance_powerup_sync_decode(packet,size,NETWORK_PERFORMANCE_SETTINGS_ACK,&enabled)) {
        assert(network_powerup_sync_client_confirmed() && enabled==host_enabled);acks++;
        if(!ack_write_success) return FALSE;
        return receive_ack(&server,&server.machines[1],packet,size);
    }
    assert(((byte const *)packet)[0]==_message_client_loaded);loaded_writes++;
    return network_game_server_handle_message_client_loaded(&server,&server.machines[1],packet,(short)size);
}
static void network_connection_keep_alive(void *connection) { (void)connection; }
static int network_game_create_game_objects(struct network_game *g) { (void)g;assert(network_powerup_sync_effective()==host_enabled);local_objects++;return TRUE; }
static int network_player_is_valid(struct network_player *p) { (void)p;return FALSE; }
static long unstrip_player_index(long p) { return p; }
static void local_player_set_player_index(int controller,long p) { (void)controller;(void)p; }
static void ui_widgets_close_all(void) { }
static void game_time_start(void) { }
static void game_time_set_distributed(long t) { (void)t; }
static int game_connection(void) { return _game_connection_network_client; }
static void game_initial_pulse(void) { }
static void network_game_invalidate(struct network_game *g) { memset(g,0,sizeof(*g)); }
static int network_connection_connected(void *c) { (void)c;return TRUE; }
static int network_connection_active(void *c) { (void)c;return TRUE; }
static int network_connection_disconnect(void *c) { (void)c;return TRUE; }
static void network_game_client_set_error(struct network_game_client *c,int e) { c->error=e; }
static void network_game_client_directory_cancel(void) { }
static void network_connection_delete(void *c) { (void)c; }
/* HOST FUNCTIONS */
static int admit(struct network_game_server *server,struct network_game_server_client_machine *server_client_machine) {
    /* ADMISSION */
    return TRUE;
}
static int receive_ack(struct network_game_server *server,struct network_game_server_client_machine *machine,word *message,unsigned message_buffer_size) {
    boolean result=FALSE;int powerup_sync_enabled;
    do { /* ACK RECEIVE */ } while(0);
    return result;
}
static void remove_slot(int i) { /* REMOVE RESET */ }
static void accept_slot(int i) { /* ACCEPT RESET */ }
static void begin_host_session(struct network_game_server *server) { /* HOST BEGIN */ }
static void end_host_session(void) { /* HOST END */ }
/* CLIENT FUNCTIONS */
static void setup(struct network_game_client *client,int enabled,int late,int supported) {
    memset(&server,0,sizeof(server));memset(client,0,sizeof(*client));memset(queues,0,sizeof(queues));
    memset(queue_count,0,sizeof(queue_count));queue_next=0;
    memset(network_game_server_performance_capabilities,0,sizeof(network_game_server_performance_capabilities));
    memset(network_game_server_powerup_sync_acknowledged,0,sizeof(network_game_server_powerup_sync_acknowledged));
    host_enabled=enabled;preference=!enabled;remote_supported=supported;local_server=NULL;
    settings_pieces=acks=loaded_writes=normal_loaded=late_loaded=object_requests=local_objects=ordinary_settings_writes=rejections=ignored_controls=0;
    ack_write_success=1;server.state=late ? _network_game_server_state_ingame:_network_game_server_state_pregame;
    for(int i=0;i<3;i++) server.machines[i].machine_index=i;
    server.machines[0].joined=server.machines[0].local=TRUE;
    server.machines[1].joined=TRUE;server.machines[1].late=late;
    server.machines[2].joined=server.machines[2].late=TRUE;
    network_game_server_performance_capability(&server.machines[1],supported ? 32767:0);
    network_game_client_performance_host_capabilities=0;network_powerup_sync_client_end();network_powerup_sync_client_begin();
    client->state=_network_game_client_state_joining;client->connection=client;
}
static void inject(unsigned kind,int enabled,int reliable) {
    queue_count[1]=1;queue_next=0;queues[1][0].size=16;queues[1][0].reliable=reliable;
    network_performance_powerup_sync_encode(queues[1][0].bytes,kind,enabled);
}
int main(void) {
    struct network_game_client client;byte game[19]={0};word loaded=0;
    for(int late=0;late<=1;late++) for(int enabled=0;enabled<=1;enabled++) {
        setup(&client,enabled,late,TRUE);
        assert(admit(&server,&server.machines[1]));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(!network_game_server_handle_message_client_loaded(&server,&server.machines[1],&loaded,2));
        assert(!normal_loaded && !late_loaded && !object_requests);
        assert(!network_game_server_powerup_sync_acknowledge(&server.machines[1],!enabled));
        assert(!network_game_server_powerup_sync_ready(&server,&server.machines[1]));
#else
        if(enabled) { assert(!network_game_server_send_powerup_sync_settings(&server,&server.machines[1]));continue; }
#endif
        if(late) assert(network_game_server_send_game_settings_to_client_machine(&server,&server.machines[1],game,sizeof(game)));
        else { assert(network_game_server_send_game_settings_to_all_machines(&server,game,sizeof(game)));assert(queue_count[2]==0); }
        unsigned flags;assert(network_performance_decode(queues[1][0].bytes,16,NETWORK_PERFORMANCE_CAPABILITY,&flags));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        int value=-1;assert(flags&NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG);
        assert(network_performance_powerup_sync_decode(queues[1][1].bytes,16,NETWORK_PERFORMANCE_SETTINGS,&value) && value==enabled);
        assert(queues[1][2].bytes[0]==_message_server_game_settings_update);
#else
        assert(!(flags&NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG));assert(queues[1][1].bytes[0]==_message_server_game_settings_update);
#endif
        assert(!network_powerup_sync_effective());int before=reads;
        assert(network_game_client_process_incoming_messages(&client));
        assert(reads==before && preference==!enabled && network_powerup_sync_effective()==enabled && settings_pieces==3);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(acks==1 && network_game_server_powerup_sync_ready(&server,&server.machines[1]));
        /* Repeated rest/settings refreshes confirm the same immutable policy. */
        assert(network_game_server_powerup_sync_acknowledge(&server.machines[1],enabled));
#else
        assert(!acks && network_game_server_powerup_sync_ready(&server,&server.machines[1]));
#endif
        client.state=_network_game_client_state_pregame;
        assert(network_game_client_game_has_started(&client));
        assert(local_objects==1 && loaded_writes==1 && object_requests==1);
        assert(late ? late_loaded==1 && !normal_loaded:normal_loaded==1 && !late_loaded);
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(acks==2); /* loading repeats ACK before loaded, including late join */
        remove_slot(1);assert(!network_game_server_powerup_sync_acknowledged[1] && !network_game_server_performance_capabilities[1]);
        network_game_server_performance_capability(&server.machines[1],32767);
        assert(!network_game_server_powerup_sync_ready(&server,&server.machines[1]));
        assert(network_game_server_powerup_sync_acknowledge(&server.machines[1],enabled));
        accept_slot(1);assert(!network_game_server_powerup_sync_acknowledged[1] && !network_game_server_performance_capabilities[1]);
        network_game_server_performance_capability(&server.machines[1],32767);
        assert(!network_game_server_powerup_sync_ready(&server,&server.machines[1]));
#endif
        network_game_client_reset(&client,TRUE);
        assert(!network_powerup_sync_controlled_by_host() && !network_powerup_sync_client_confirmed());
        assert(network_powerup_sync_effective()==preference && !network_game_client_performance_host_capabilities);
        network_powerup_sync_client_begin();assert(network_powerup_sync_client_apply(enabled));
        network_game_client_dont_use_directly_in_use=TRUE;network_game_client_dispose(&client);
        assert(!network_powerup_sync_controlled_by_host() && network_powerup_sync_effective()==preference);
    }
    /* Old peers receive the original full-settings-only stream when Off. */
    setup(&client,0,0,FALSE);assert(admit(&server,&server.machines[1]));
    assert(network_game_server_send_game_settings_to_client_machine(&server,&server.machines[1],game,sizeof(game)));
    assert(queue_count[1]==3 && queues[1][0].bytes[0]==_message_server_game_settings_update);
    assert(network_game_client_process_incoming_messages(&client));
    assert(!acks && !network_powerup_sync_effective() && preference==1);
    assert(network_game_server_handle_message_client_loaded(&server,&server.machines[1],&loaded,2));
    setup(&client,1,1,FALSE);assert(preference==0);
    assert(!admit(&server,&server.machines[1]) && rejections==1);
    assert(!network_game_server_send_powerup_sync_settings(&server,&server.machines[1]));
    assert(!network_game_server_handle_message_client_loaded(&server,&server.machines[1],&loaded,2));
    assert(!object_requests);
    assert(network_game_server_powerup_sync_ready(&server,&server.machines[0]));
    assert(network_game_server_send_powerup_sync_settings(&server,&server.machines[0]));
    assert(!network_game_server_powerup_sync_ready(NULL,&server.machines[0]));
    assert(!network_game_server_powerup_sync_ready(&server,NULL));
    /* Only a capable established host on the reliable stream may apply it. */
    setup(&client,1,0,TRUE);inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    assert(network_game_client_process_incoming_messages(&client));
    assert(!acks && !network_powerup_sync_client_confirmed()); /* no host capability */
    network_game_client_performance_host_capabilities=32767;
    inject(NETWORK_PERFORMANCE_SETTINGS,1,FALSE);
    assert(network_game_client_process_incoming_messages(&client));
    assert(ignored_controls==1 && !acks && !network_powerup_sync_client_confirmed());
    client.state=_network_game_client_state_searching;inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    assert(network_game_client_process_incoming_messages(&client) && !network_powerup_sync_client_confirmed());
    client.state=_network_game_client_state_joining;local_server=&server;
    inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    assert(network_game_client_process_incoming_messages(&client) && !network_powerup_sync_client_confirmed());
    local_server=NULL;ack_write_success=0;inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    assert(!network_game_client_process_incoming_messages(&client));
    assert(network_powerup_sync_client_confirmed() && network_powerup_sync_effective());
    assert(!network_game_server_powerup_sync_ready(&server,&server.machines[1]) && !object_requests);
    ack_write_success=1;inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    assert(network_game_client_process_incoming_messages(&client));
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
    assert(network_game_server_powerup_sync_ready(&server,&server.machines[1]));
#else
    assert(!network_game_server_powerup_sync_ready(&server,&server.machines[1]));
#endif
    inject(NETWORK_PERFORMANCE_SETTINGS,0,TRUE);
    assert(!network_game_client_process_incoming_messages(&client) && network_powerup_sync_effective());
    /* V7 mixed flags must never enter the saved Performance record. */
    client.state=_network_game_client_state_pregame;inject(NETWORK_PERFORMANCE_SETTINGS,1,TRUE);
    queues[1][0].bytes[13]=NETWORK_PERFORMANCE_HARDCORE_FLAG;
    assert(network_game_client_process_incoming_messages(&client));
    assert(!ordinary_settings_writes && network_powerup_sync_effective());
    inject(NETWORK_PERFORMANCE_SETTINGS,0,TRUE);
    network_performance_encode(queues[1][0].bytes,NETWORK_PERFORMANCE_SETTINGS,NETWORK_PERFORMANCE_SELF_MOVEMENT_FLAG);
    assert(network_game_client_process_incoming_messages(&client));
    assert(ordinary_settings_writes==2 && runtime_variant.flags==NETWORK_PERFORMANCE_SELF_MOVEMENT_FLAG);
    assert(network_powerup_sync_effective() && !preference);
    /* ACKs must match this connected machine and never authenticate another. */
    word ack[8];network_performance_powerup_sync_encode((byte *)ack,NETWORK_PERFORMANCE_SETTINGS_ACK,0);
    assert(!receive_ack(&server,&server.machines[1],ack,16));
    network_performance_powerup_sync_encode((byte *)ack,NETWORK_PERFORMANCE_SETTINGS_ACK,1);
    server.machines[1].joined=FALSE;
    assert(!receive_ack(&server,&server.machines[1],ack,16));
    assert(!network_game_server_powerup_sync_acknowledge(NULL,1));
    server.machines[1].machine_index=NONE;
    assert(!network_game_server_powerup_sync_acknowledge(&server.machines[1],1));
    /* Hosting after a remote session takes the saved preference and clears
       every prior connection's ACK before any new objects can be admitted. */
    network_powerup_sync_client_end();network_powerup_sync_client_begin();
    assert(network_powerup_sync_client_apply(0));preference=1;
    for(int i=0;i<3;i++) network_game_server_powerup_sync_acknowledged[i]=TRUE;
    begin_host_session(&server);
    assert(!network_powerup_sync_controlled_by_host() && network_powerup_sync_effective());
    for(int i=0;i<3;i++) assert(!network_game_server_powerup_sync_acknowledged[i]);
    preference=0;assert(network_powerup_sync_effective() && network_powerup_sync_pending());
    end_host_session();assert(!network_powerup_sync_effective() && !network_powerup_sync_pending());
    return 0;
}
'''


class PowerupHostSettingsTests(unittest.TestCase):
    def test_failed_remote_connect_and_local_listen_server_join_lifecycle(self):
        source = (ROOT / "source/networking/network_client_manager.c").read_text()
        source = source[source.index("/* ---------- public code */"):]
        initiate = block(source, "boolean network_game_client_initiate_join_game(\n")
        fixture = r'''
#include <assert.h>
#include <string.h>
#include "networking/network_powerup_sync.h"
#include "networking/network_performance_protocol.h"
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16
#define MAXIMUM_NETWORK_ADVERTISED_GAMES 1
#define VALID_INDEX(i,n) ((i)>=0 && (i)<(n))
#define csmemcpy memcpy
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
enum { _network_game_client_state_searching=0,_network_game_client_state_joining=1 };
struct network_advertised_game { int platform; };
struct network_join_parameters { int marker; };
struct transport_address { int marker; };
struct network_game_client {
    int state,join_in_progress,connect_process;
    unsigned long connection_attempt_time;
    void *connection;
    struct network_advertised_game available_games[1];
    struct network_join_parameters join_parameters;
};
static unsigned network_game_client_performance_host_capabilities;
static boolean network_game_client_cache_offer_valid,network_game_client_cache_settings_pending,network_game_client_cache_begin_pending;
static boolean network_game_client_original_rules_host;
static struct { unsigned flags; } network_game_client_advertised_versions[1];
static int preference,connect_result,keep_alives,connection_attempts,error_dialogs,listen_server;
int config_boolean(char const *name) { assert(!strcmp(name,"network.experimental_powerup_sync"));return preference; }
int config_write_boolean(char const *name,int value) { (void)name;(void)value;assert(0);return 0; }
static void *global_network_game_server_get(void) { return listen_server ? &listen_server:NULL; }
static int network_connection_connected(void *connection) { assert(connection);return FALSE; }
static int network_game_get_local_platform(void) { return 1; }
static unsigned long system_milliseconds(void) { return 12345; }
static int network_connection_connect(void *connection,struct transport_address *address,int flags) {
    assert(connection && address->marker==77 && flags==0);connection_attempts++;return connect_result;
}
static void network_connection_keep_alive(void *connection) { assert(connection);keep_alives++; }
static void display_error_when_main_menu_loaded(int error) { assert(error==7);error_dialogs++; }
/* INITIATE JOIN */
static void prepare(struct network_game_client *client) {
    memset(client,0,sizeof(*client));client->connection=client;client->available_games[0].platform=1;
    network_game_client_performance_host_capabilities=32767;
    network_game_client_cache_offer_valid=network_game_client_cache_settings_pending=network_game_client_cache_begin_pending=TRUE;
    keep_alives=connection_attempts=error_dialogs=0;
}
int main(void) {
    struct network_game_client client;struct transport_address address={77};
    struct network_join_parameters parameters={99};
    network_powerup_sync_host_end();listen_server=FALSE;
    for(int saved=0;saved<=1;saved++) for(int success=0;success<=1;success++) {
        preference=saved;network_powerup_sync_client_begin();
        assert(network_powerup_sync_client_apply(!saved)); /* stale prior remote session */
        assert(network_powerup_sync_controlled_by_host() && network_powerup_sync_client_confirmed());
        prepare(&client);connect_result=success;
        assert(network_game_client_initiate_join_game(&client,&client.available_games[0],&parameters,&address)==success);
        assert(connection_attempts==1 && keep_alives==success && error_dialogs==!success);
        assert(client.join_parameters.marker==99 && client.connection_attempt_time==12345 && !client.connect_process);
        assert(client.join_in_progress==success && client.state==success);
        assert(!network_game_client_performance_host_capabilities && !network_powerup_sync_client_confirmed());
#ifdef HALO_PORT_MAXIMUM_NETWORK_PLAYERS
        assert(!network_game_client_cache_offer_valid && !network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending);
#endif
        assert(preference==saved);
        if(success) {
            assert(network_powerup_sync_controlled_by_host() && !network_powerup_sync_effective());
            assert(network_powerup_sync_client_apply(!saved));
            assert(network_powerup_sync_effective()==!saved && preference==saved);
        } else {
            assert(!network_powerup_sync_controlled_by_host()); /* still locally editable after failure */
            assert(network_powerup_sync_effective()==saved && !network_powerup_sync_client_apply(!saved));
        }
        network_powerup_sync_client_end();
    }
    /* Both successful loopback connection and a failed loopback attempt leave
       the already hosted session latched; neither installs a remote override. */
    preference=1;network_powerup_sync_host_begin();preference=0;listen_server=TRUE;
    for(int success=0;success<=1;success++) {
        prepare(&client);connect_result=success;
        assert(network_game_client_initiate_join_game(&client,&client.available_games[0],&parameters,&address)==success);
        assert(network_powerup_sync_host_enabled() && network_powerup_sync_effective() && network_powerup_sync_pending());
        assert(!network_powerup_sync_controlled_by_host() && !network_powerup_sync_client_confirmed());
        assert(preference==0 && !network_powerup_sync_client_apply(0));
    }
    network_powerup_sync_host_end();assert(!network_powerup_sync_effective());return 0;
}
'''
        fixture = fixture.replace("/* INITIATE JOIN */", initiate)
        for native in (True, False):
            with self.subTest(native_queue=native):
                run_fixture(fixture if native else fixture.replace("#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16", ""),
                            production=(ROOT / "source/networking/network_powerup_sync.c",))

    def test_lobby_late_join_policy_before_settings_and_ack_before_objects(self):
        fixture = network_fixture_source()
        for native in (True, False):
            with self.subTest(native_queue=native):
                run_fixture(fixture if native else fixture.replace("#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 16", ""),
                            production=(ROOT / "source/networking/network_powerup_sync.c",))

    def test_v7_policy_ack_validation_and_peer_support(self):
        run_fixture(r'''
#include <assert.h>
#include <string.h>
#include "networking/network_performance_protocol.h"
int main(void) {
    for(unsigned kind=NETWORK_PERFORMANCE_SETTINGS;kind<=NETWORK_PERFORMANCE_SETTINGS_ACK;kind++)
        for(int enabled=0;enabled<=1;enabled++) {
            unsigned char encoded[16],bad[16];int decoded=-1;
            unsigned char expected[16]={8,1,0xe0,1,0,0,0,0,'H','P','F','O',7,0,0,0};
            expected[14]=(unsigned char)kind;expected[15]=enabled ? 64:0;
            network_performance_powerup_sync_encode(encoded,kind,enabled);
            assert(!memcmp(encoded,expected,sizeof(encoded)));
            assert(network_performance_powerup_sync_decode(encoded,16,kind,&decoded) && decoded==enabled);
            assert(!network_performance_powerup_sync_decode(encoded,15,kind,&decoded));
            assert(!network_performance_powerup_sync_decode(encoded,17,kind,&decoded));
            assert(!network_performance_powerup_sync_decode(encoded,16,kind==2 ? 3:2,&decoded));
            assert(!network_performance_powerup_sync_decode(encoded,16,NETWORK_PERFORMANCE_CAPABILITY,&decoded));
            assert(!network_performance_powerup_sync_decode(NULL,16,kind,&decoded));
            assert(!network_performance_powerup_sync_decode(encoded,16,kind,NULL));
            for(unsigned i=4;i<=12;i++) {
                memcpy(bad,encoded,16);bad[i]^=1;
                assert(!network_performance_powerup_sync_decode(bad,16,kind,&decoded));
            }
            memcpy(bad,encoded,16);bad[13]=NETWORK_PERFORMANCE_HARDCORE_FLAG;
            assert(!network_performance_powerup_sync_decode(bad,16,kind,&decoded));
            memcpy(bad,encoded,16);bad[15]|=128;
            assert(!network_performance_powerup_sync_decode(bad,16,kind,&decoded));
        }
    assert(network_performance_capability_for_peer(32767,1,1,1,1,1,1,1,0)==16383);
    assert(network_performance_capability_for_peer(32767,1,1,1,1,1,1,1,1)==32767);
    assert(!network_performance_can_join(NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG,16383));
    assert(network_performance_can_join(NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG,32767));
    assert(network_performance_can_join(0,0));
    assert(network_performance_advertised_version(NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG,11)==NETWORK_PERFORMANCE_ADVERTISED_VERSION);
    assert(network_performance_advertised_version(0,11)==11);
    assert(!(network_performance_runtime_supported_flags(0,0)&NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG));
    assert(network_performance_runtime_supported_flags(1,0)&NETWORK_PERFORMANCE_POWERUP_SYNC_FLAG);
    return 0;
}
''')

    def test_host_latching_client_override_and_session_reset(self):
        run_fixture(r'''
#include <assert.h>
#include <string.h>
#include "networking/network_powerup_sync.h"
static int preference,reads;
int config_boolean(char const *name) { assert(!strcmp(name,"network.experimental_powerup_sync"));reads++;return preference; }
/* Session synchronization must never persist a received host value. */
int config_write_boolean(char const *name,int value) { (void)name;(void)value;assert(0);return 0; }
int main(void) {
    network_powerup_sync_client_end();network_powerup_sync_host_end();
    preference=0;assert(!network_powerup_sync_effective() && !network_powerup_sync_host_enabled());
    assert(!network_powerup_sync_client_apply(1));
    network_powerup_sync_host_begin();assert(!network_powerup_sync_pending());
    preference=1;assert(!network_powerup_sync_effective() && network_powerup_sync_pending());
    assert(!network_powerup_sync_controlled_by_host() && !network_powerup_sync_host_enabled());
    network_powerup_sync_host_end();network_powerup_sync_host_begin();
    assert(network_powerup_sync_effective() && network_powerup_sync_host_enabled() && !network_powerup_sync_pending());
    preference=0;assert(network_powerup_sync_effective() && network_powerup_sync_pending());
    network_powerup_sync_host_end();assert(!network_powerup_sync_pending() && !network_powerup_sync_host_enabled());
    for(int local=0;local<=1;local++) for(int host=0;host<=1;host++) {
        preference=local;network_powerup_sync_client_begin();
        assert(network_powerup_sync_controlled_by_host() && !network_powerup_sync_effective());
        assert(!network_powerup_sync_client_confirmed() && !network_powerup_sync_pending());
        int before=reads;assert(network_powerup_sync_client_apply(host));
        assert(network_powerup_sync_effective()==host && network_powerup_sync_client_confirmed());
        assert(network_powerup_sync_client_apply(host)); /* Reliable retransmission is idempotent. */
        assert(!network_powerup_sync_client_apply(!host)); /* A session cannot change rules mid-match. */
        assert(network_powerup_sync_effective()==host && reads==before && preference==local);
        network_powerup_sync_client_end();assert(!network_powerup_sync_controlled_by_host());
        assert(!network_powerup_sync_client_confirmed() && network_powerup_sync_effective()==local);
        network_powerup_sync_client_begin();assert(!network_powerup_sync_effective() && !network_powerup_sync_client_confirmed());
        assert(network_powerup_sync_client_apply(!host) && network_powerup_sync_effective()==!host);
        network_powerup_sync_client_end();
    }
    preference=1;network_powerup_sync_client_begin();assert(network_powerup_sync_client_apply(0));
    network_powerup_sync_host_begin(); /* A listen server's local client cannot override host ownership. */
    assert(network_powerup_sync_effective() && !network_powerup_sync_controlled_by_host());
    assert(!network_powerup_sync_client_apply(0));
    network_powerup_sync_client_end();network_powerup_sync_host_end();
    preference=0;network_powerup_sync_host_begin();assert(!network_powerup_sync_effective());
    network_powerup_sync_host_end();return 0;
}
''', production=(ROOT / "source/networking/network_powerup_sync.c",))

    def test_older_capability_and_settings_frames_remain_byte_identical(self):
        run_fixture(r'''
#include <assert.h>
#include <string.h>
#include "networking/network_performance_protocol.h"
int main(void) {
    unsigned const flags[]={3,7,31,63,127,255,511,1023,2047,4095,16383};
    unsigned const versions[]={1,1,1,1,1,1,2,3,4,5,6};
    for(unsigned i=0;i<sizeof(flags)/sizeof(flags[0]);i++) {
        unsigned char expected[16]={8,1,0xe0,1,0,0,0,0,'H','P','F','O',0,0,1,0};
        expected[12]=(unsigned char)versions[i];expected[13]=(unsigned char)flags[i];expected[15]=(unsigned char)(flags[i]>>8);
        unsigned char encoded[16];unsigned decoded=0;
        network_performance_encode(encoded,NETWORK_PERFORMANCE_CAPABILITY,flags[i]);
        assert(!memcmp(expected,encoded,sizeof(encoded)));
        assert(network_performance_decode(encoded,sizeof(encoded),NETWORK_PERFORMANCE_CAPABILITY,&decoded) && decoded==flags[i]);
    }
    unsigned char expected_settings[16]={8,1,0xe0,1,0,0,0,0,'H','P','F','O',1,0,2,0};
    unsigned char encoded[16];unsigned decoded=123;
    network_performance_encode(encoded,NETWORK_PERFORMANCE_SETTINGS,0);
    assert(!memcmp(encoded,expected_settings,sizeof(encoded)));
    assert(network_performance_decode(encoded,sizeof(encoded),NETWORK_PERFORMANCE_SETTINGS,&decoded) && decoded==0);
    return 0;
}
''')


if __name__ == "__main__":
    unittest.main()
