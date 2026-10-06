"""Exercise production v11 settings layout, reassembly and admission boundaries.

The guest's long and wchar are 32/16 bits. Fixtures substitute fixed-width
types for host execution; socket transport and full game loading need runtime
validation separately. Optional match rules retain the original variant layout.
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
#include "halo_port_limits.h"
#include "networking/network_performance_protocol.h"
#include "networking/network_expanded_cache_protocol.h"
typedef unsigned char byte, boolean;
typedef unsigned short word;
typedef float real;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define FLAG(bit) (1U<<(bit))
#define TEST_FLAG(value,bit) ((value)&FLAG(bit))
#define SET_FLAG(value,bit,on) ((value)=(on)?((value)|FLAG(bit)):((value)&~FLAG(bit)))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define csmemset memset
#define csmemcpy memcpy
#define csstrcmp strcmp
#define _stricmp strcmp
#define csprintf(destination,...) snprintf(destination,sizeof(destination),__VA_ARGS__)
#define VALID_INDEX(i,n) ((i)>=0 && (i)<(n))
#define MAXIMUM_ODDBALLS 16
#define MAXIMUM_NETWORK_MACHINE_COUNT 128
#define MAXIMUM_NUMBER_OF_PLAYERS 128
#define NUMBER_OF_GAME_DIFFICULTY_LEVELS 4
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define _error_network_failed_to_join_game 7
#define match_assert(file,line,condition) assert(condition)
#define network_event(...) ((void)0)
enum { _game_variant_draw_object_in_motion_sensor_bit=0, _game_variant_infinite_grenades_bit=2 };
enum { _performance_option_input_delay=32, _performance_option_hardcore=64, _performance_option_fiesta=128,
       _performance_option_hardcore_camo=256, PERFORMANCE_MATCH_RULE_FLAGS=480,
       _starting_equipment_fiesta=2, _starting_equipment_generic=1, _starting_equipment_custom=0,
       _network_game_client_state_joining=1, _network_game_client_state_pregame=2,
       _network_game_client_state_ingame=3, _network_game_client_state_postgame=4,
       _network_game_server_state_pregame=1, _network_game_server_state_ingame=2, _network_game_server_state_postgame=3,
       _network_client_machine_precached_bit=3, _message_client_loaded=10,
       NETWORK_GAME_MESSAGE_VERSION=1, _network_game_packet_class_client_ingame=2 };
/* WEAPON SET IDS */
/* DECLARATIONS */
#include "game/game_variant_options.h"
struct network_player { byte wire[32]; };
/* RECORD */
struct network_game_client { struct network_game game; int state; void *connection; };
struct network_game_server_client_machine { unsigned supported; boolean joined,loading_late,closed,acknowledged,local,offered,loaded; word flags; };
struct network_game_server { struct network_game game; struct network_game_server_client_machine machines[MAXIMUM_NETWORK_MACHINE_COUNT]; int state; };
static struct network_game_client client;
static struct network_game_server *active_server;
static unsigned network_game_client_performance_host_capabilities;
static struct network_game network_game_client_settings_staging;
static int32_t network_game_client_settings_staging_size;
static unsigned precaches, dialogs, applied, applied_flags, errors;
static unsigned sent_capabilities, sent_settings_pieces, sent_offers, sent_ready;
static struct native_map_cache_selection selected_cache, server_cache;
static struct network_expanded_cache_identity network_game_client_cache_offer;
static boolean network_game_client_cache_offer_valid;
static struct network_game network_game_client_cache_settings;
static struct network_expanded_cache_identity network_game_client_cache_settings_offer;
static boolean network_game_client_cache_settings_pending, network_game_client_cache_begin_pending;
static unsigned long network_game_client_cache_wait_started, network_game_client_cache_retry_time, network_game_client_cache_heartbeat_time;
static unsigned pending_packets, resumed_starts, matching_heartbeats;
static int download_status, prepare_status;
static unsigned char requested_digest[32];
static unsigned long fixture_now=999;
static boolean network_game_client_defer_cache_begin(void);
#define network_game_server_cache_selection server_cache
static unsigned asset_digest=42;
static unsigned load_decodes, normal_loaded, late_loaded;
struct message_client_loaded { word unused; };
static short network_game_server_get_state(struct network_game_server *server,void *data) { (void)data;return (short)server->state; }
static boolean network_game_server_client_machine_is_loaded(struct network_game_server *server,
    struct network_game_server_client_machine *machine) { (void)server;return machine->loaded; }
static boolean decode_network_game_message(void *record,word *message,short *size,short *kind,short *version,int packet) {
    (void)record;(void)message;(void)size;assert(*kind==_message_client_loaded && *version==NETWORK_GAME_MESSAGE_VERSION && packet==2);
    load_decodes++;return TRUE;
}
static void network_game_server_client_machine_game_loading_complete(struct network_game_server *s,
    struct network_game_server_client_machine *m) { (void)s;m->loaded=TRUE;normal_loaded++; }
static void network_game_server_late_joiner_loaded(struct network_game_server *s,
    struct network_game_server_client_machine *m) { (void)s;m->loaded=TRUE;late_loaded++; }
static char const *main_get_multiplayer_map_name(void) { return "chillout"; }
static boolean missing_cache, cache_loaded=TRUE;
static unsigned char ready_packet[NETWORK_EXPANDED_CACHE_MESSAGE_SIZE];
int native_map_cache_prepare(char const *map,struct game_variant const *variant,
    struct native_map_cache_selection *selection,int show) {
    (void)show;memset(selection,0,sizeof(*selection));
    snprintf(selection->logical_name,32,"%s",map);snprintf(selection->physical_name,32,"%s",map);
    if(native_map_cache_uses_global_arsenal(variant)) {
        if(missing_cache) return FALSE;
        selection->expanded=1;selection->generation=HALO_EXPANDED_CACHE_GENERATION;
        snprintf(selection->physical_name,32,"_fiesta_%s",map);
        memset(selection->sha256,(int)asset_digest,32);memset(selection->weapon_list_sha256,23,32);
    }
    return TRUE;
}
int native_map_cache_prepare_expected(char const *map,struct game_variant const *variant,
    unsigned char const *expected,struct native_map_cache_selection *selection,int show) {
    if(expected)memcpy(requested_digest,expected,32);
    int ready=native_map_cache_prepare(map,variant,selection,show);
    if(ready && expected && memcmp(expected,selection->sha256,32))ready=FALSE;
    prepare_status=ready?1:download_status;return ready;
}
int native_map_cache_download_status(void) { return prepare_status; }
static char const *native_map_basename(char const *map) {
    char const *name=map;for(char const *p=map;*p;p++)if(*p=='/' || *p=='\\')name=p+1;return name;
}
static boolean network_game_client_game_has_started(struct network_game_client *c) {
    if(network_game_client_defer_cache_begin())return TRUE;
    assert(!network_game_client_cache_settings_pending && selected_cache.expanded);
    assert(native_map_cache_selection_equal(&selected_cache,&network_game_client_cache_offer.selection));
    resumed_starts++;c->state=_network_game_client_state_ingame;return TRUE;
}
static void network_game_server_client_machine_heard(struct network_game_server *s,
    struct network_game_server_client_machine *m) { (void)s;(void)m;matching_heartbeats++; }
void native_map_cache_select(struct native_map_cache_selection const *s) { selected_cache=*s; }
struct native_map_cache_selection const *native_map_cache_current(void) { return &selected_cache; }
static struct native_map_cache_selection const *network_game_server_get_cache_selection(struct network_game_server *s) {
    (void)s;return &server_cache;
}
static boolean network_game_server_client_machine_is_local(struct network_game_server *s,
    struct network_game_server_client_machine *m) { (void)s;return m->local; }
static boolean cache_files_precache_map_loaded(char const *name) { (void)name;return cache_loaded; }
static boolean network_game_client_receive_cache_identity(struct network_game_client *,const byte *,unsigned,boolean);
static boolean network_game_client_write(void *connection,void const *packet,unsigned size,void *context,int reliable) {
    (void)connection;(void)context;assert(reliable && size==sizeof(ready_packet));
    memcpy(ready_packet,packet,size);
    if(((byte const *)packet)[13]==NETWORK_EXPANDED_CACHE_DOWNLOAD_PENDING)pending_packets++;
    else sent_ready++;
    return TRUE;
}
static boolean fail_capability_send;
static struct network_game_server_client_machine *capability_failure_target;
static boolean network_game_settings_update_pending;
static unsigned long network_game_settings_update_time;
static unsigned long system_milliseconds(void) { return fixture_now; }
static struct message_server_game_settings_update encoded_settings_piece;
enum { _message_server_game_settings_update=8 };
static boolean network_game_client_receive_performance_capability(
    const struct network_game_client *, const byte *, unsigned, boolean);
static boolean network_game_client_receive_game_settings_piece(
    struct network_game_client *, const struct message_server_game_settings_update *);
static int halo_performance_audio_available(void) { return TRUE; }
static boolean network_game_server_performance_supported(
    struct network_game_server_client_machine *machine, unsigned required) {
    return network_performance_can_join(required,machine->supported);
}
static struct network_game_server_client_machine *network_game_server_get_client_machine_at_index(
    struct network_game_server *server, long index) {
    assert(index>=0 && index<MAXIMUM_NETWORK_MACHINE_COUNT);return &server->machines[index];
}
static boolean network_game_server_client_machine_is_joined_to_game(
    struct network_game_server *server, struct network_game_server_client_machine *machine) {
    (void)server;return machine->joined;
}
static boolean network_game_server_machine_is_loading_late(
    struct network_game_server *server, struct network_game_server_client_machine *machine) {
    (void)server;return machine->loading_late;
}
static void *create_network_game_message(unsigned kind,const void *data,unsigned size) {
    assert(kind==_message_server_game_settings_update && size==sizeof(encoded_settings_piece));
    memcpy(&encoded_settings_piece,data,size); return &encoded_settings_piece;
}
static boolean network_game_server_send_message_to_client_machine(
    struct network_game_server *server, struct network_game_server_client_machine *machine, void *message) {
    (void)server; (void)machine;
    if(message==&encoded_settings_piece) {
        assert(!(machine->supported & PERFORMANCE_MATCH_RULE_FLAGS) || machine->acknowledged);
        if(native_map_cache_uses_global_arsenal(&server->game.variant)) assert(machine->offered);
        sent_settings_pieces++;
        return network_game_client_receive_game_settings_piece(&client,&encoded_settings_piece);
    }
    assert(!sent_settings_pieces);
    if(((byte const *)message)[2]==NETWORK_EXPANDED_CACHE_MESSAGE_TYPE) {
        assert(machine->acknowledged);sent_offers++;machine->offered=TRUE;
        return network_game_client_receive_cache_identity(&client,message,NETWORK_EXPANDED_CACHE_MESSAGE_SIZE,TRUE);
    }
    sent_capabilities++;
    if(fail_capability_send && (!capability_failure_target || machine==capability_failure_target)) {
        machine->closed=TRUE;return FALSE;
    }
    machine->acknowledged=TRUE;
    return network_game_client_receive_performance_capability(&client,message,16,TRUE);
}
static boolean network_game_server_send_message_to_all_machines(
    struct network_game_server *server, void *message) {
    boolean result=TRUE;
    for(long index=0;index<MAXIMUM_NETWORK_MACHINE_COUNT;index++) {
        struct network_game_server_client_machine *machine=&server->machines[index];
        if(machine->joined && !machine->loading_late && !machine->closed)
            result &= network_game_server_send_message_to_client_machine(server,machine,message);
    }
    return result;
}
static int network_game_client_map_name_is_valid(const char *name, unsigned size) {
    return name[0] && memchr(name,0,size)!=NULL;
}
static int network_game_is_splitscreen_local(void) { return 0; }
static int cache_files_map_plays_multiplayer(const char *map,char *build) {
    (void)map; (void)build; return 1;
}
static void cache_files_show_multiplayer_unavailable(const char *map,const char *build) {
    (void)map; (void)build; assert(0);
}
static void main_set_multiplayer_map_name(const char *map) { (void)map; precaches++;cache_loaded=TRUE; }
static struct network_game_server *global_network_game_server_get(void) { return active_server; }
static struct network_game *network_game_server_get_game(struct network_game_server *s) { return &s->game; }
static unsigned performance_variant_get_flags(const struct game_variant *v) { return v->flags; }
static void platform_show_message(char const *title,char const *message) {
    (void)title;(void)message;dialogs++;
}
static void performance_variant_set_flags(struct game_variant *v, unsigned flags) { v->flags=flags; }
static void performance_options_apply_host_flags(unsigned flags) { applied_flags=flags; applied++; }
static void display_error_when_main_menu_loaded(unsigned error) {
    assert(error==7); errors++;
}
enum { game_engine_ctf, game_engine_slayer, game_engine_oddball, game_engine_king, game_engine_race };
static void *game_engine;
static struct { int32_t postgame_state; } game_engine_globals;
static boolean game_engine_network_state_read;
static unsigned match_endings;
static boolean read_host_state=TRUE;
static int game_engine_get_type(void) { return game_engine_slayer; }
static boolean game_engine_slayer_read_network_state(const byte *buffer,int32_t size,boolean first) {
    (void)buffer; (void)size; (void)first; return read_host_state;
}
#define game_engine_ctf_read_network_state game_engine_slayer_read_network_state
#define game_engine_oddball_read_network_state game_engine_slayer_read_network_state
#define game_engine_king_read_network_state game_engine_slayer_read_network_state
#define game_engine_race_read_network_state game_engine_slayer_read_network_state
static void game_engine_end_game(void) { match_endings++; game_engine_globals.postgame_state=1; }
struct player_datum {
    int32_t team_index,unit_index,local_player_index,powerup_durations[2],action_result,action_object_index;
};
struct unit_datum {
    struct { int32_t owner_player_index; short owner_team_index; } object;
    struct { int32_t player_index; } unit;
};
static struct player_datum test_player;
static struct unit_datum test_unit;
static boolean team_game;
enum { _player_action_result_reload=3 };
static struct player_datum *player_get(int32_t index) { assert(index==7); return &test_player; }
static struct unit_datum *unit_get(int32_t index) { assert(index==12); return &test_unit; }
static boolean game_engine_has_teams(void) { return team_game; }
static void unit_set_actively_controlled(int32_t index,boolean active) { assert(index==12 && active); }
static void player_control_new_unit(int32_t local,int32_t index) { assert(local==0 && index==12); }
static void observer_obsolete_position(int32_t local) { assert(local==0); }
/* FUNCTIONS */
'''

HARNESS = r'''
static struct network_game defaults(void) {
    struct network_game game={0};
    strcpy(game.map.name,"chillout"); game.machine_count=2; game.player_count=2;
    game.difficulty=1; game.variant.universal_variant.vehicle_set=2;
    game_variant_options_default(&game.variant,&game.variant_options);
    return game;
}
static void reset(void) {
    memset(&client,0,sizeof(client));
    network_game_client_performance_host_capabilities=0;
    precaches=dialogs=applied=applied_flags=errors=0; active_server=NULL;
    sent_capabilities=sent_settings_pieces=sent_offers=sent_ready=0; fail_capability_send=FALSE;
    memset(&selected_cache,0,sizeof(selected_cache));memset(&server_cache,0,sizeof(server_cache));
    memset(&network_game_client_cache_offer,0,sizeof(network_game_client_cache_offer));
    network_game_client_cache_offer_valid=FALSE;missing_cache=FALSE;cache_loaded=TRUE;asset_digest=42;
    network_game_client_cache_settings_pending=network_game_client_cache_begin_pending=FALSE;
    pending_packets=resumed_starts=matching_heartbeats=0;download_status=prepare_status=0;fixture_now=999;
    memset(requested_digest,0,sizeof(requested_digest));
    load_decodes=normal_loaded=late_loaded=0;
    capability_failure_target=NULL;
    network_game_settings_update_pending=FALSE;network_game_settings_update_time=0;
    network_game_client_settings_staging_size=0;
}
static void wire(void) {
    assert(HALO_PORT_NETWORK_VERSION==11);
    assert(sizeof(struct network_game)==13120);
    assert(offsetof(struct network_game,variant_options)==HALO_PORT_NETWORK_GAME_VARIANT_OPTIONS_OFFSET);
    assert(offsetof(struct network_game,local_data)==HALO_PORT_NETWORK_GAME_LOCAL_DATA_OFFSET);
    assert(sizeof(struct game_variant_options)==28);
    assert(offsetof(struct game_variant_options,radar_players)==9);
    assert(offsetof(struct game_variant_options,loadout)==24);
    assert((NETWORK_PERFORMANCE_ADVERTISED_FLAG & HALO_PORT_ADVERTISED_IN_PROGRESS_FLAG)==0);
    assert(network_performance_advertised_version(0,11)==11);
    assert(network_performance_advertised_version(1,11)==0x800B);
    assert(network_performance_version_compatible(0x800B,4,11));
    assert(!network_performance_version_compatible(0x800B,2,11));
    assert(!network_performance_version_compatible(0x800A,4,11));
    assert(!network_performance_version_compatible(10,4,11));
    byte encoded[16]; unsigned flags;
    network_performance_encode(encoded,NETWORK_PERFORMANCE_SETTINGS,31);
    assert(network_performance_decode(encoded,16,NETWORK_PERFORMANCE_SETTINGS,&flags) && flags==31);
}
static void options(void) {
    struct network_game game=defaults();
    const byte expected[28]={0,0,0,0,0,0,0,0,0,2,2,2,0,0,0,0,0,0,0,0,0,0,0,0,0,2,3,0};
    assert(!memcmp(expected,&game.variant_options,28));
    assert(!game_variant_options_unsupported(&game.variant,&game.variant_options));
    for(unsigned field=0;field<28;field++) {
        struct game_variant_options changed=game.variant_options;
        ((byte *)&changed)[field]++;
        /* Host-controlled options are accepted; counts, category weapons and
         * padding are inactive. A high-byte friendly-fire change is invalid. */
        assert((game_variant_options_unsupported(&game.variant,&changed)!=NULL)==
            (field==3 || (field>=9 && field<12) || field==24));
    }
    game.variant.universal_variant.flags=1;
    game_variant_options_default(&game.variant,&game.variant_options);
    assert(game.variant_options.radar_players==0);
    for(int set=0;set<=12;set++) {
        game.variant.universal_variant.weapon_set=set;
        assert(!game_variant_options_unsupported(&game.variant,&game.variant_options));
    }
    game.variant.universal_variant.weapon_set=13;
    assert(strstr(game_variant_options_unsupported(&game.variant,&game.variant_options),"weapon set"));
}
static void admission(void) {
    struct network_game game=defaults(); reset();
    client.game.local_data.game_objects_loaded=1;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(precaches==1 && applied==1 && client.game.local_data.game_objects_loaded==1);
    struct network_game before=client.game;
    strcpy(game.map.name,"bloodgulch"); game.player_count=MAXIMUM_NUMBER_OF_PLAYERS+1;
    assert(!network_game_client_game_settings_updated(&client,&game));
    assert(precaches==1 && applied==1 && !dialogs);
    assert(!memcmp(&before,&client.game,sizeof(before)));
    game=defaults(); game.player_count=16; game.variant.universal_variant.flags=4;
    assert(network_game_client_game_settings_updated(&client,&game));
}
static void host_time_limit(void) {
    const short limits[]={0,1,10,32767};
    for(unsigned i=0;i<sizeof(limits)/sizeof(limits[0]);i++) {
        struct network_game game=defaults(); reset();
        game.variant_options.time_limit=limits[i];
        assert(network_game_client_game_settings_updated(&client,&game));
        assert(client.game.variant_options.time_limit==limits[i]);
        assert(precaches==1 && applied==1 && !dialogs && !errors);
        /* Differing rules no longer block admission during live testing. */
        game.variant_options.loadout=1;
        assert(network_game_client_game_settings_updated(&client,&game));
        assert(!dialogs && !errors);
    }
    struct network_game game=defaults();
    assert(game.variant_options.time_limit==0);
}
static void active_input_delay(void) {
    struct network_game game=defaults(); reset();
    network_game_client_performance_host_capabilities=63;
    client.state=_network_game_client_state_ingame;
    client.game=defaults(); client.game.variant.flags=32;
    game.variant.flags=7; game.variant_options.time_limit=15;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==39 && applied_flags==39);
    assert(client.game.variant_options.time_limit==15);
    client.game.variant.flags=7; game.variant.flags=39;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==7 && applied_flags==7);
    /* A joining client is pregame while receiving the active host's rules;
     * it must accept that match's delay before beginning simulation. */
    client.state=_network_game_client_state_pregame;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==39 && applied_flags==39);
    client.state=_network_game_client_state_postgame; game.variant.flags=0;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==0 && applied_flags==0);
    /* The same full-record path fixes Fiesta for an active match, while a
     * late join adopts it in pregame before simulation begins. */
    network_game_client_performance_host_capabilities=255;
    client.state=_network_game_client_state_ingame;client.game.variant.flags=128;
    game.variant.flags=7;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==135 && applied_flags==135);
    client.game.variant.flags=7;game.variant.flags=135;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==7 && applied_flags==7);
    client.state=_network_game_client_state_pregame;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==135 && applied_flags==135);
    network_game_client_performance_host_capabilities=511;
    client.state=_network_game_client_state_ingame;client.game.variant.flags=256;
    game.variant.flags=7;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==263 && applied_flags==263);
    client.game.variant.flags=7;game.variant.flags=263;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==7 && applied_flags==7);
    client.state=_network_game_client_state_pregame;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.flags==263 && applied_flags==263);
}
static void host_delay_acknowledgement(void) {
    const unsigned unknown_flags[]={32,39,64,96,127,128,135,255,256,263,511};
    for(unsigned i=0;i<sizeof(unknown_flags)/sizeof(unknown_flags[0]);i++) {
        struct network_game game=defaults(); reset();
        client.state=_network_game_client_state_pregame;
        game.variant.flags=unknown_flags[i];game.variant_options.time_limit=15;game.variant_options.loadout=1;
        assert(network_game_client_game_settings_updated(&client,&game));
        assert(client.game.variant.flags==0 && applied_flags==0);
        assert(client.game.variant_options.time_limit==15 && client.game.variant_options.loadout==1);
    }
    /* A new host's acknowledgement remains decodable by the mask-63
     * generation. It cannot advertise Hardcore to that older peer. */
    {
        struct network_game_server legacy_host={.game=defaults()};
        struct network_game_server_client_machine legacy_peer={.supported=63};
        reset();client.state=_network_game_client_state_pregame;
        legacy_host.game.variant.flags=32;
        assert(network_game_server_send_game_settings_to_client_machine(&legacy_host,&legacy_peer,
            &legacy_host.game,sizeof(legacy_host.game)));
        assert(network_game_client_performance_host_capabilities==63);
        assert(client.game.variant.flags==32 && applied_flags==32);
        assert(!network_performance_can_join(64,63));
        assert(network_performance_can_join(64,127));
        assert(network_performance_host_settings_flags(71,63)==0);
        byte malformed[16];unsigned decoded;
        network_performance_encode(malformed,NETWORK_PERFORMANCE_SETTINGS,128);
        malformed[12]++;
        assert(!network_performance_decode(malformed,16,NETWORK_PERFORMANCE_SETTINGS,&decoded));
    }
    /* Hardcore peers still decode their 127-bit acknowledgement. A prior
     * host may forward unknown Fiesta padding, but runs that whole extension
     * Off; the client must follow the acknowledged host rather than the save. */
    {
        struct network_game_server legacy_host={.game=defaults()};
        struct network_game_server_client_machine legacy_peer={.supported=127};
        reset();client.state=_network_game_client_state_pregame;
        legacy_host.game.variant.flags=71;
        assert(network_game_server_send_game_settings_to_client_machine(&legacy_host,&legacy_peer,
            &legacy_host.game,sizeof(legacy_host.game)));
        assert(network_game_client_performance_host_capabilities==127);
        assert(client.game.variant.flags==71 && applied_flags==71);
        assert(!network_performance_can_join(128,127));
        assert(network_performance_can_join(128,255));
        assert(network_performance_host_settings_flags(135,127)==0);
        struct network_game forwarded=defaults();forwarded.variant.flags=135;
        assert(network_game_client_game_settings_updated(&client,&forwarded));
        assert(client.game.variant.flags==0 && applied_flags==0);
    }
    /* The last version-1 generation gets byte-identical mask-255 support.
     * It can forward saved v2 padding, but must not enable Camo or its aids. */
    {
        struct network_game_server legacy_host={.game=defaults()};
        struct network_game_server_client_machine legacy_peer={.supported=255};
        reset();client.state=_network_game_client_state_pregame;
        legacy_host.game.variant.flags=135;
        assert(network_game_server_send_game_settings_to_client_machine(&legacy_host,&legacy_peer,
            &legacy_host.game,sizeof(legacy_host.game)));
        assert(network_game_client_performance_host_capabilities==255);
        assert(client.game.variant.flags==135 && applied_flags==135);
        assert(!network_performance_can_join(256,255));
        assert(network_performance_can_join(256,511));
        struct network_game forwarded=defaults();forwarded.variant.flags=263;
        assert(network_game_client_game_settings_updated(&client,&forwarded));
        assert(client.game.variant.flags==0 && applied_flags==0);
    }
    /* The actual sender and reassembler establish support before applying
     * saved delay, without any discovery advertisement. Direct late joins
     * use this per-client serializer before their begin-game packet. */
    for(unsigned flags=0;flags<=511;flags++) {
        struct network_game_server host={.game=defaults()};
        struct network_game_server_client_machine machine={.supported=511};
        reset();client.state=_network_game_client_state_pregame;
        host.game.variant.flags=flags;
        assert(network_game_server_send_game_settings_to_client_machine(&host,&machine,&host.game,sizeof(host.game)));
        assert(sent_capabilities==1 && sent_settings_pieces>1);
        assert(network_game_client_performance_host_capabilities==511);
        assert(client.game.variant.flags==flags && applied_flags==flags && applied==1);
    }
    /* No acknowledgement is sent to stock/older clients with all options
     * Off. A failed acknowledgement stops the record before its first byte. */
    struct network_game_server host={.game=defaults()};
    struct network_game_server_client_machine machine={.supported=31};
    reset();client.state=_network_game_client_state_pregame;
    assert(network_game_server_send_game_settings_to_client_machine(&host,&machine,&host.game,sizeof(host.game)));
    assert(!sent_capabilities && sent_settings_pieces>1 && applied==1 && applied_flags==0);
    reset();client.state=_network_game_client_state_pregame;machine.supported=127;fail_capability_send=TRUE;
    assert(!network_game_server_send_game_settings_to_client_machine(&host,&machine,&host.game,sizeof(host.game)));
    assert(sent_capabilities==1 && !sent_settings_pieces && !applied);
}
static void normal_start_delay_acknowledgement(void) {
    /* Normal starts and lobby updates have a separate broadcast serializer.
     * Exercise it directly: stubbing it previously hid a missing handshake. */
    for(unsigned flags=0;flags<=511;flags++) {
        struct network_game_server host={.game=defaults()};
        host.machines[1]=(struct network_game_server_client_machine){.supported=511,.joined=TRUE};
        reset();client.state=_network_game_client_state_pregame;
        host.game.variant.flags=flags;
        assert(network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
        assert(sent_capabilities==1 && sent_settings_pieces>1);
        assert(network_game_client_performance_host_capabilities==511);
        assert(client.game.variant.flags==flags && applied_flags==flags && applied==1);
        assert(!network_game_settings_update_pending && network_game_settings_update_time==999);
    }
    struct network_game_server host={.game=defaults()};
    host.machines[1]=(struct network_game_server_client_machine){.supported=31,.joined=TRUE};
    reset();client.state=_network_game_client_state_pregame;
    assert(network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
    assert(!sent_capabilities && sent_settings_pieces>1 && applied==1 && applied_flags==0);
    reset();client.state=_network_game_client_state_pregame;
    host.machines[1].supported=127;fail_capability_send=TRUE;
    assert(!network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
    assert(sent_capabilities==1 && !sent_settings_pieces && !applied && network_game_settings_update_pending);
    /* One failed stream cannot keep a healthy peer on its old variant. */
    host=(struct network_game_server){.game=defaults()};host.game.variant.flags=32;
    host.machines[0]=(struct network_game_server_client_machine){.supported=127,.joined=TRUE};
    host.machines[1]=(struct network_game_server_client_machine){.supported=127,.joined=TRUE};
    reset();client.state=_network_game_client_state_pregame;
    fail_capability_send=TRUE;capability_failure_target=&host.machines[0];
    assert(!network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
    assert(sent_capabilities==2 && sent_settings_pieces>1 && applied==1 && applied_flags==32);
    assert(host.machines[0].closed && !host.machines[1].closed && network_game_settings_update_pending);
}
static void expanded_weapon_acknowledgement(void) {
    for(int set=GAME_WEAPON_SET_UNCUT;set<=GAME_WEAPON_SET_ALL;set++) {
        for(unsigned flags=0;flags<=128;flags+=128) {
            struct network_game_server host={.game=defaults()};
            host.game.variant.universal_variant.weapon_set=set;host.game.variant.flags=flags;
            unsigned required=flags|512|(flags?1024:0), supported=flags?2047:1023;
            assert(network_game_variant_required_capabilities(&host.game.variant)==required);
            assert(!network_performance_can_join(required,511));
            assert(network_performance_can_join(required,supported));
            assert(!flags || !network_performance_can_join(required,1023));
            assert(network_performance_advertised_version(required,11)==0x800B);
            reset();client.state=_network_game_client_state_pregame;
            assert(!network_game_client_game_settings_updated(&client,&host.game));
            assert(!precaches && !applied && errors==1 && dialogs==1);
            network_game_client_performance_host_capabilities=511;
            assert(!network_game_client_game_settings_updated(&client,&host.game));
            assert(!precaches && !applied && errors==2 && dialogs==2);
            struct network_game_server_client_machine peer={.supported=supported};
            reset();client.state=_network_game_client_state_pregame;
            assert(native_map_cache_prepare(host.game.map.name,&host.game.variant,&server_cache,1));
            assert(network_game_server_send_game_settings_to_client_machine(&host,&peer,&host.game,sizeof(host.game)));
            assert(sent_capabilities==1 && sent_offers==(flags?1U:0U) && sent_settings_pieces>1 && precaches==1 && applied==1);
            assert(network_game_client_performance_host_capabilities==supported);
            assert(client.game.variant.flags==flags && client.game.variant.universal_variant.weapon_set==set);
            host.machines[1]=(struct network_game_server_client_machine){.supported=supported,.joined=TRUE};
            reset();client.state=_network_game_client_state_pregame;
            assert(native_map_cache_prepare(host.game.map.name,&host.game.variant,&server_cache,1));
            assert(network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
            assert(sent_capabilities==1 && sent_offers==(flags?1U:0U) && sent_settings_pieces>1 && precaches==1 && applied==1);
            assert(network_game_client_performance_host_capabilities==supported);
            assert(client.game.variant.flags==flags && client.game.variant.universal_variant.weapon_set==set);
            reset();client.state=_network_game_client_state_pregame;fail_capability_send=TRUE;
            assert(!network_game_server_send_game_settings_to_all_machines(&host,&host.game,sizeof(host.game)));
            assert(sent_capabilities==1 && !sent_offers && !sent_settings_pieces && !precaches && !applied);
        }
    }
    struct network_game game=defaults();reset();client.game=game;
    client.state=_network_game_client_state_ingame;
    network_game_client_performance_host_capabilities=1023;
    client.game.variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    game.variant.universal_variant.weapon_set=GAME_WEAPON_SET_UNCUT;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.universal_variant.weapon_set==GAME_WEAPON_SET_ALL);
    game.variant.universal_variant.weapon_set=0;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(client.game.variant.universal_variant.weapon_set==GAME_WEAPON_SET_ALL);
}
static void global_cache_identity(void) {
    struct network_game game=defaults();game.variant.flags=128;
    game.variant.universal_variant.weapon_set=GAME_WEAPON_SET_ALL;
    reset();client.state=_network_game_client_state_pregame;
    network_game_client_performance_host_capabilities=1023;
    assert(!network_game_client_game_settings_updated(&client,&game));
    assert(!precaches && !selected_cache.expanded);
    network_game_client_performance_host_capabilities=2047;
    assert(!network_game_client_game_settings_updated(&client,&game));
    assert(!precaches && !selected_cache.expanded);
    assert(native_map_cache_prepare(game.map.name,&game.variant,&server_cache,1));
    byte offer[160];network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&server_cache,12);
    assert(!network_game_client_receive_cache_identity(&client,offer,160,FALSE));
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    struct network_game before=client.game;
    asset_digest=43;
    assert(!network_game_client_game_settings_updated(&client,&game));
    assert(!precaches && !memcmp(&before,&client.game,sizeof(before)) && !selected_cache.expanded);
    asset_digest=42;missing_cache=TRUE;
    assert(!network_game_client_game_settings_updated(&client,&game));assert(!precaches);
    missing_cache=FALSE;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(precaches==1 && native_map_cache_selection_equal(&selected_cache,&server_cache));
    cache_loaded=FALSE;assert(!network_game_client_send_cache_ready(&client));assert(!sent_ready);
    cache_loaded=TRUE;assert(network_game_client_send_cache_ready(&client));assert(sent_ready==1);
    struct network_expanded_cache_identity ready;
    assert(network_expanded_cache_decode(ready_packet,160,NETWORK_EXPANDED_CACHE_READY,&ready));
    assert(ready.weapon_set==12 && native_map_cache_selection_equal(&ready.selection,&server_cache));
    client.state=_network_game_client_state_ingame;
    struct native_map_cache_selection changed=server_cache;changed.sha256[0]++;
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&changed,11);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    assert(network_game_client_cache_offer.weapon_set==12);
    strcpy(game.map.name,"prisoner");before=client.game;
    assert(!network_game_client_game_settings_updated(&client,&game));assert(!memcmp(&before,&client.game,sizeof(before)));
    /* Shared host resolver already selected global data before its local full
       record: absent physical cache must still trigger same-map precache. */
    struct network_game_server host={.game=defaults()};host.game.variant=client.game.variant;
    client.state=_network_game_client_state_pregame;client.game=defaults();
    active_server=&host;cache_loaded=FALSE;precaches=0;
    assert(network_game_client_game_settings_updated(&client,&host.game));
    assert(precaches==1 && cache_loaded);
    /* Turning Fiesta off on the same logical map restores original identity. */
    active_server=NULL;game=host.game;game.variant.flags=0;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(precaches==2 && !selected_cache.expanded && !strcmp(selected_cache.physical_name,"chillout"));
}
static void global_cache_download_wait(void) {
    struct network_game game=defaults(),before;
    struct network_game_server host={.game=defaults(),.state=_network_game_server_state_ingame};
    byte offer[160];
    game.variant.flags=128;game.variant.universal_variant.weapon_set=12;
    reset();client.state=_network_game_client_state_pregame;client.game=defaults();before=client.game;
    network_game_client_performance_host_capabilities=4095;
    assert(native_map_cache_prepare(game.map.name,&game.variant,&server_cache,1));host.game=game;
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&server_cache,12);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    missing_cache=TRUE;download_status=2;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(network_game_client_cache_settings_pending && !precaches && !applied && !sent_ready);
    assert(!memcmp(&client.game,&before,sizeof(before)) && !memcmp(requested_digest,server_cache.sha256,32));
    assert(network_game_client_defer_cache_begin() && network_game_client_cache_begin_pending && !resumed_starts);
    assert(!network_game_client_send_cache_ready(&client));
    assert(network_game_client_retry_cache_settings(&client));assert(pending_packets==1 && !sent_ready);
    struct network_expanded_cache_identity heartbeat;
    assert(network_expanded_cache_decode(ready_packet,160,NETWORK_EXPANDED_CACHE_DOWNLOAD_PENDING,&heartbeat));
    struct network_game_server_client_machine machine={.supported=4095,.joined=TRUE};
    assert(network_game_server_client_machine_cache_pending(&host,&machine,&heartbeat));
    assert(matching_heartbeats==1 && !network_game_server_client_machine_has_cache_identity(&host,&machine));
    heartbeat.selection.sha256[0]++;
    assert(network_game_server_client_machine_cache_pending(&host,&machine,&heartbeat));assert(matching_heartbeats==1);
    machine.supported=2047;assert(!network_game_server_client_machine_cache_pending(&host,&machine,&heartbeat));
    machine.supported=4095;machine.joined=FALSE;assert(!network_game_server_client_machine_cache_pending(&host,&machine,&heartbeat));
    missing_cache=FALSE;fixture_now+=1000;
    assert(network_game_client_retry_cache_settings(&client));
    assert(!network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending && resumed_starts==1);
    assert(precaches==1 && applied==1 && client.state==_network_game_client_state_ingame);
    /* A v4 host remains usable with local content, but cannot keep missing-content joins alive. */
    reset();client.state=_network_game_client_state_pregame;network_game_client_performance_host_capabilities=2047;
    assert(native_map_cache_prepare(game.map.name,&game.variant,&server_cache,1));
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&server_cache,12);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    missing_cache=TRUE;download_status=2;
    assert(!network_game_client_game_settings_updated(&client,&game));assert(!network_game_client_cache_settings_pending && !precaches);
    missing_cache=FALSE;assert(network_game_client_game_settings_updated(&client,&game));assert(precaches==1);
}
static void global_cache_download_cancellation(void) {
    struct network_game game=defaults();byte offer[160];
    game.variant.flags=128;game.variant.universal_variant.weapon_set=11;
    reset();client.state=_network_game_client_state_pregame;network_game_client_performance_host_capabilities=4095;
    assert(native_map_cache_prepare(game.map.name,&game.variant,&server_cache,1));
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&server_cache,11);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    missing_cache=TRUE;download_status=2;
    assert(network_game_client_game_settings_updated(&client,&game));assert(network_game_client_defer_cache_begin());
    unsigned long started=network_game_client_cache_wait_started;
    fixture_now+=1000;assert(network_game_client_game_settings_updated(&client,&game));
    assert(network_game_client_cache_wait_started==started);
    struct native_map_cache_selection replacement=server_cache;replacement.sha256[31]++;
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&replacement,11);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    assert(!network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending);
    assert(network_game_client_retry_cache_settings(&client));assert(!resumed_starts && !precaches);
    network_expanded_cache_encode(offer,NETWORK_EXPANDED_CACHE_OFFER,&server_cache,11);
    assert(network_game_client_receive_cache_identity(&client,offer,160,TRUE));
    assert(network_game_client_game_settings_updated(&client,&game));assert(network_game_client_defer_cache_begin());
    game.variant.flags=0;assert(network_game_client_game_settings_updated(&client,&game));
    assert(!network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending && !resumed_starts);
    game.variant.flags=128;assert(network_game_client_game_settings_updated(&client,&game));assert(network_game_client_defer_cache_begin());
    fixture_now=network_game_client_cache_wait_started+15*60*1000+1;
    assert(!network_game_client_retry_cache_settings(&client));
    assert(!network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending && !resumed_starts);
    fixture_now+=1;assert(network_game_client_game_settings_updated(&client,&game));
    assert(network_game_client_defer_cache_begin());download_status=-1;fixture_now+=1000;
    assert(!network_game_client_retry_cache_settings(&client));
    assert(!network_game_client_cache_settings_pending && !network_game_client_cache_begin_pending && !resumed_starts);
}
static void global_cache_ready_admission(void) {
    struct network_game_server host={.game=defaults(),.state=_network_game_server_state_pregame};
    host.game.variant.flags=128;host.game.variant.universal_variant.weapon_set=11;
    reset();assert(native_map_cache_prepare(host.game.map.name,&host.game.variant,&server_cache,1));
    struct network_game_server_client_machine machine={.supported=2047,.joined=TRUE};
    word loaded[2]={0};
    network_game_server_client_machine_is_precached(&host,&machine,"chillout");
    assert(!network_game_server_client_machine_has_cache_identity(&host,&machine));
    assert(!network_game_server_handle_message_client_loaded(&host,&machine,loaded,sizeof(loaded)));
    assert(!load_decodes && !normal_loaded);
    struct network_expanded_cache_identity ready={.selection=server_cache,.weapon_set=11};
    for(unsigned field=0;field<4;field++) {
        struct network_expanded_cache_identity changed=ready;
        if(field==0) changed.selection.sha256[31]++;
        if(field==1) changed.selection.weapon_list_sha256[31]++;
        if(field==2) changed.weapon_set=12;
        if(field==3) changed.selection.generation++;
        assert(!network_game_server_client_machine_cache_ready(&host,&machine,&changed));
        assert(!network_game_server_client_machine_has_cache_identity(&host,&machine));
    }
    machine.supported=1023;
    assert(!network_game_server_client_machine_cache_ready(&host,&machine,&ready));
    machine.supported=2047;machine.joined=FALSE;
    assert(!network_game_server_client_machine_cache_ready(&host,&machine,&ready));
    machine.joined=TRUE;
    assert(network_game_server_client_machine_cache_ready(&host,&machine,&ready));
    assert(network_game_server_handle_message_client_loaded(&host,&machine,loaded,sizeof(loaded)));
    assert(load_decodes==1 && normal_loaded==1);
    host.state=_network_game_server_state_ingame;machine.flags=0;machine.loaded=FALSE;
    assert(!network_game_server_handle_message_client_loaded(&host,&machine,loaded,sizeof(loaded)));
    assert(!late_loaded);
    assert(network_game_server_client_machine_cache_ready(&host,&machine,&ready));
    assert(network_game_server_handle_message_client_loaded(&host,&machine,loaded,sizeof(loaded)));
    assert(late_loaded==1);
    host.game.variant.flags=0;machine.flags=0;
    network_game_server_client_machine_is_precached(&host,&machine,"chillout");
    assert(network_game_server_client_machine_has_cache_identity(&host,&machine));
}
static void host_match_end(void) {
    int32_t state=0;
    game_engine=&state; game_engine_globals.postgame_state=0;
    game_engine_network_state_read=FALSE; match_endings=0; read_host_state=TRUE;
    game_engine_read_network_state((byte *)&state,sizeof(state));
    assert(game_engine_network_state_read && !match_endings);
    state=1; read_host_state=FALSE;
    game_engine_read_network_state((byte *)&state,sizeof(state));
    assert(!match_endings);
    read_host_state=TRUE;
    game_engine_read_network_state((byte *)&state,sizeof(state)-1);
    assert(!match_endings);
    game_engine_read_network_state((byte *)&state,sizeof(state));
    assert(match_endings==1 && game_engine_globals.postgame_state==1);
    game_engine_read_network_state((byte *)&state,sizeof(state));
    assert(match_endings==1);
}
static void host_authority_options(void) {
    struct network_game game=defaults(); reset();
    game.variant_options.time_limit=15;
    game.variant_options.friendly_fire=3;
    game.variant_options.friendly_fire_penalty=10;
    game.variant_options.vehicle_respawn_time=30;
    game.variant_options.auto_team_balance=1;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(!memcmp(&client.game.variant_options,&game.variant_options,sizeof(game.variant_options)));
    assert(precaches==1 && applied==1 && !dialogs && !errors);
    struct network_game before=client.game;
    /* Structural validation must still happen before live state changes. */
    game.machine_count=MAXIMUM_NETWORK_MACHINE_COUNT+1;
    assert(!network_game_client_game_settings_updated(&client,&game));
    assert(!memcmp(&client.game,&before,sizeof(before)) && precaches==1 && applied==1);
    game=defaults();
    game.variant_options.radar_players=1;
    game.variant_options.vehicle_set[0]=255;
    game.variant_options.vehicle_set[1]=3;
    game.variant_options.vehicle_counts[0][0]=4;
    game.variant_options.loadout=1;
    game.variant_options.primary_weapon=5;
    game.variant_options.secondary_weapon=8;
    game.variant.universal_variant.weapon_set=11;
    network_game_client_performance_host_capabilities=1023;
    assert(network_game_client_game_settings_updated(&client,&game));
    assert(!memcmp(&client.game.variant_options,&game.variant_options,sizeof(game.variant_options)));
    assert(client.game.variant.universal_variant.weapon_set==11 && !dialogs);
    const short valid_seconds[]={0,1,30,32767};
    for(unsigned i=0;i<sizeof(valid_seconds)/sizeof(valid_seconds[0]);i++) {
        game=defaults();
        game.variant_options.friendly_fire_penalty=valid_seconds[i];
        game.variant_options.vehicle_respawn_time=valid_seconds[i];
        for(short mode=0;mode<=3;mode++) {
            game.variant_options.friendly_fire=mode;
            assert(!game_variant_options_unsupported(&game.variant,&game.variant_options));
        }
    }
    game=defaults(); game.variant_options.friendly_fire=-1;
    assert(game_variant_options_unsupported(&game.variant,&game.variant_options));
    game.variant_options.friendly_fire=4;
    assert(game_variant_options_unsupported(&game.variant,&game.variant_options));
    game=defaults(); game.variant_options.friendly_fire_penalty=-1;
    assert(game_variant_options_unsupported(&game.variant,&game.variant_options));
    game=defaults(); game.variant_options.auto_team_balance=2;
    assert(game_variant_options_unsupported(&game.variant,&game.variant_options));
    game=defaults();
    assert(!game.variant_options.friendly_fire && !game.variant_options.friendly_fire_penalty);
    assert(!game.variant_options.vehicle_respawn_time && !game.variant_options.auto_team_balance);
}
static void host_team_assignment(void) {
    team_game=TRUE;
    for(short team=0;team<2;team++) {
        memset(&test_player,0,sizeof(test_player)); memset(&test_unit,0,sizeof(test_unit));
        test_player.team_index=1-team; test_player.local_player_index=0;
        test_unit.object.owner_team_index=team;
        network_player_attach_unit(7,12);
        assert(test_player.team_index==team && test_unit.object.owner_team_index==team);
        assert(test_player.unit_index==12 && test_unit.unit.player_index==7);
        assert(test_unit.object.owner_player_index==7);
    }
    const short invalid_teams[]={-1,2,127};
    for(unsigned i=0;i<sizeof(invalid_teams)/sizeof(invalid_teams[0]);i++) {
        test_player.team_index=0; test_unit.object.owner_team_index=invalid_teams[i];
        network_player_attach_unit(7,12);
        assert(test_player.team_index==0 && test_unit.object.owner_team_index==0);
    }
    team_game=FALSE; test_player.team_index=7; test_unit.object.owner_team_index=1;
    network_player_attach_unit(7,12);
    assert(test_player.team_index==7 && test_unit.object.owner_team_index==7);
}
static int send_record(struct network_game *game) {
    int result=1;
    for(unsigned offset=0;offset<sizeof(*game);offset+=HALO_PORT_NETWORK_GAME_SETTINGS_FRAGMENT_SIZE) {
        struct message_server_game_settings_update piece={0};
        piece.total_size=sizeof(*game); piece.offset=offset;
        piece.length=sizeof(*game)-offset;
        if(piece.length>sizeof(piece.data)) piece.length=sizeof(piece.data);
        memcpy(piece.data,(byte *)game+offset,piece.length);
        result=network_game_client_receive_game_settings_piece(&client,&piece);
        if(offset+piece.length<sizeof(*game)) assert(!applied && !precaches);
    }
    return result;
}
static void fragments(void) {
    struct network_game game=defaults(); reset();
    assert(send_record(&game) && applied==1 && precaches==1);
    reset(); game.variant_options.time_limit=10;
    game.variant_options.friendly_fire=1;
    game.variant_options.friendly_fire_penalty=5;
    game.variant_options.vehicle_respawn_time=60;
    game.variant_options.auto_team_balance=1;
    assert(send_record(&game) && applied==1 && precaches==1);
    assert(client.game.variant_options.time_limit==10 && !dialogs);
    assert(!memcmp(&client.game.variant_options,&game.variant_options,sizeof(game.variant_options)));
    reset(); game.variant_options.loadout=1;
    game.variant_options.vehicle_set[0]=255; game.variant_options.vehicle_set[1]=3;
    assert(send_record(&game) && applied==1 && precaches==1 && !dialogs);
    assert(!memcmp(&client.game.variant_options,&game.variant_options,sizeof(game.variant_options)));
    reset(); struct message_server_game_settings_update piece={0};
    piece.total_size=13092; piece.length=1;
    assert(!network_game_client_receive_game_settings_piece(&client,&piece));
    piece.total_size=sizeof(game); piece.offset=1;
    assert(network_game_client_receive_game_settings_piece(&client,&piece));
    assert(!applied && !precaches && !network_game_client_settings_staging_size);
    piece.offset=sizeof(game)-1; piece.length=2;
    assert(!network_game_client_receive_game_settings_piece(&client,&piece));
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strcmp(argv[1],"wire")) wire();
    else if(!strcmp(argv[1],"options")) options();
    else if(!strcmp(argv[1],"admission")) admission();
    else if(!strcmp(argv[1],"fragments")) fragments();
    else if(!strcmp(argv[1],"host-time-limit")) host_time_limit();
    else if(!strcmp(argv[1],"active-input-delay")) active_input_delay();
    else if(!strcmp(argv[1],"host-delay-acknowledgement")) host_delay_acknowledgement();
    else if(!strcmp(argv[1],"normal-start-delay-acknowledgement")) normal_start_delay_acknowledgement();
    else if(!strcmp(argv[1],"expanded-weapon-acknowledgement")) expanded_weapon_acknowledgement();
    else if(!strcmp(argv[1],"global-cache-identity")) global_cache_identity();
    else if(!strcmp(argv[1],"global-cache-ready-admission")) global_cache_ready_admission();
    else if(!strcmp(argv[1],"global-cache-download-wait")) global_cache_download_wait();
    else if(!strcmp(argv[1],"global-cache-download-cancellation")) global_cache_download_cancellation();
    else if(!strcmp(argv[1],"host-match-end")) host_match_end();
    else if(!strcmp(argv[1],"host-authority-options")) host_authority_options();
    else if(!strcmp(argv[1],"host-team-assignment")) host_team_assignment();
    else assert(0);
    return 0;
}
'''


class NetworkV11Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-v11-")
        cls.addClassCleanup(cls.directory.cleanup)
        engine = (ROOT / "source/game/game_engine.h").read_text()
        names = ("universal_variant", "ctf_variant", "slayer_variant", "king_variant", "oddball_variant", "race_variant")
        declarations = "\n".join(block(engine, f"struct {name}\n") + ";" for name in names)
        declarations += "\n" + block(engine, "union game_engine_variant\n") + ";"
        declarations += "\n" + block(engine, "struct game_variant\n") + ";"
        manager = (ROOT / "source/networking/network_game_manager.h").read_text()
        record = "\n".join(block(manager, f"struct {name}\n") + ";" for name in (
            "network_machine", "network_game_map", "network_game_local_data", "network_game"))
        client = (ROOT / "source/networking/network_client_manager.c").read_text()
        handler = (ROOT / "source/networking/network_client_message_handler.c").read_text()
        record += "\n" + block(handler, "struct message_server_game_settings_update\n") + ";"
        weapons = (ROOT / "source/game/weapon_sets.h").read_text()
        required = (ROOT / "source/networking/network_variant_capabilities.h").read_text()
        functions = block(weapons, "static inline int game_variant_uses_expanded_weapon_set(\n")
        functions += "\n" + block(required, "static inline unsigned network_game_variant_required_capabilities(\n")
        functions += "\n" + block((ROOT / "source/game/starting_equipment.h").read_text(), "static inline short starting_equipment_get(")
        expanded = (ROOT / "port/linux/game/expanded_cache.c").read_text()
        functions += "\n" + block(expanded, "int native_map_cache_uses_global_arsenal(")
        functions += "\n" + block(expanded, "int native_map_cache_selection_equal(")
        functions += "\n" + block(client, "static boolean network_game_client_receive_performance_capability(\n")
        functions += "\n" + block(client, "static boolean network_game_client_receive_cache_identity(")
        functions += "\n" + block(client, "static boolean network_game_client_send_cache_ready(")
        functions += "\n" + block(client, "static boolean network_game_client_defer_cache_settings(")
        functions += "\n" + block(client, "static boolean network_game_client_defer_cache_begin(")
        functions += "\n" + block(client, "static unsigned network_game_client_performance_settings_flags(\n")
        functions += "\n" + block(client, "boolean network_game_client_game_settings_updated(\n")
        functions += "\n" + block(client, "static boolean network_game_client_retry_cache_settings(")
        functions += "\n" + block(handler, "static boolean network_game_client_receive_game_settings_piece(\n")
        server_handler = (ROOT / "source/networking/network_server_message_handler.c").read_text()
        functions += "\n" + block(server_handler, "static boolean network_game_server_send_performance_capability(\n")
        server_manager = (ROOT / "source/networking/network_server_manager.c").read_text()
        functions += "\n" + block(server_manager, "boolean network_game_server_client_machine_cache_ready(")
        functions += "\n" + block(server_manager, "boolean network_game_server_client_machine_cache_pending(")
        functions += "\n" + block(server_manager, "boolean network_game_server_client_machine_has_cache_identity(")
        functions += "\n" + block(server_manager, "void network_game_server_client_machine_is_precached(")
        loaded_signature = "static boolean network_game_server_handle_message_client_loaded("
        functions += "\n" + block(server_handler[server_handler.rindex(loaded_signature):], loaded_signature)
        functions += "\n" + block(server_handler, "static boolean network_game_server_send_cache_identity(")
        functions += "\n" + block(server_handler, "boolean network_game_server_send_game_settings_to_client_machine(\n")
        functions += "\n" + block(server_handler, "boolean network_game_server_send_game_settings_to_all_machines(\n")
        functions += "\n" + block((ROOT / "source/game/game_engine.c").read_text(), "void game_engine_read_network_state(\n")
        functions += "\n" + block((ROOT / "source/game/players.c").read_text(), "void network_player_attach_unit(\n")
        source = PREFIX.replace("/* DECLARATIONS */", declarations).replace("/* RECORD */", record)
        source = source.replace("/* WEAPON SET IDS */", block(weapons, "enum\n") + ";")
        source = source.replace("/* FUNCTIONS */", functions) + HARNESS
        source = re.sub(r"\blong\b", "int32_t", source).replace("unsigned int32_t", "uint32_t")
        source = source.replace("wchar_t", "uint16_t")
        path = Path(cls.directory.name) / "v11.c"
        path.write_text(source)
        cls.executable = path.with_suffix(".exe" if sys.platform == "win32" else "")
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise AssertionError("A native C compiler is required")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
        result = subprocess.run([
            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
            "-I", str(ROOT / "source"), "-iquote", str(ROOT / "port/linux/include"),
            str(path), "-o", str(cls.executable),
        ], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, case):
        result = subprocess.run([str(self.executable), case], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wire_layout_and_pb_namespace(self):
        self.run_case("wire")

    def test_original_defaults_and_active_option_boundaries(self):
        self.run_case("options")

    def test_reject_before_precache_and_live_state_change(self):
        self.run_case("admission")

    def test_fragment_reassembly_and_mixed_version_rejection(self):
        self.run_case("fragments")

    def test_host_time_limit_acceptance_preserves_other_boundaries(self):
        self.run_case("host-time-limit")

    def test_full_settings_keep_active_input_delay(self):
        self.run_case("active-input-delay")

    def test_host_support_precedes_saved_variant_for_starts_and_late_joins(self):
        self.run_case("host-delay-acknowledgement")

    def test_normal_start_broadcast_acknowledges_before_settings(self):
        self.run_case("normal-start-delay-acknowledgement")

    def test_expanded_weapon_sets_require_host_ack_before_loading(self):
        self.run_case("expanded-weapon-acknowledgement")

    def test_global_cache_offer_readiness_and_same_map_transitions(self):
        self.run_case("global-cache-identity")

    def test_exact_revision_download_wait_and_nonready_heartbeat(self):
        self.run_case("global-cache-download-wait")

    def test_download_reoffer_timeout_failure_and_stale_begin_cancellation(self):
        self.run_case("global-cache-download-cancellation")

    def test_full_cache_ready_echo_precedes_normal_and_late_loaded_admission(self):
        self.run_case("global-cache-ready-admission")

    def test_client_ends_match_on_valid_host_state(self):
        self.run_case("host-match-end")

    def test_host_controlled_rules_acceptance_and_validation(self):
        self.run_case("host-authority-options")

    def test_spawn_takes_valid_host_team_assignment(self):
        self.run_case("host-team-assignment")


if __name__ == "__main__":
    unittest.main()
