"""Production original-menu adapter for OG directory and signed OpenCE listings.

The upstream provider owns Ed25519/sequence/expiry validation, covered by
p2p_lobby_check.c. This fixture supplies its authenticated snapshots and runs
the actual combined list and invite/peer/real-ad join adapter without sockets.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class OpenCEDiscoveryTests(unittest.TestCase):
    def test_combined_original_list_and_authenticated_join(self):
        p2p = (ROOT / "port/linux/src/p2p.c").read_text()
        functions = block(p2p, "static int parse_invite(")
        functions += "\n" + block(p2p, "int p2p_invite_identity(")
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "p2p.h"
#include "game_directory.h"
typedef uint8_t byte;typedef uint16_t word;typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define HALO_PORT_NETWORK_VERSION 22
#define NETWORK_PERFORMANCE_ADVERTISED_VERSION 0x8016
#define MAXIMUM_NETWORK_ADVERTISED_GAMES 9
#define NETWORK_GAME_NAME_LENGTH 16
#define NETWORK_GAME_MAP_NAME_LENGTH 64
#define _network_game_client_state_searching 2
#define _network_game_platform_xbox 0
#define csmemset memset
#define csmemcmp memcmp
#define csmemcpy memcpy
#define csstrcmp strcmp
#define csstrncpy strncpy
#define ustrncpy wcsncpy
#define P2P_KEY_HASH_SIZE 16
#define P2P_TOKEN_SIZE 16
#define P2P_IDENTIFIER_SIZE 6
typedef struct {byte size,flags,abEnet[6];uint32_t ina;} XNADDR;
_Static_assert(sizeof(XNADDR)==12,"Xbox address");
struct network_advertised_game {
 XNADDR xnaddr;wchar_t game_name[16];struct {char name[64];} map;
 short engine_type,maximum_player_count,machine_count,platform,unknown100;
 word player_count;boolean open,has_teams,valid,oddball_variant;unsigned long update_time;
};
struct network_game_client {int state;struct network_advertised_game available_games[9];};
static struct halo_directory_game og[64];static struct p2p_listing stock[64];
static int og_count,stock_count,og_browsing,stock_browsing,requested,connected,errors;
static char requested_invite[P2P_LINK_SIZE];
static unsigned long milliseconds=100,peer_address=0x1020304;
static unsigned long system_milliseconds(void) {return milliseconds;}
static void network_event(const char *text) {(void)text;}
static boolean network_game_client_advertised_game_is_valid(struct network_advertised_game *game) {return game->valid;}
void game_directory_browse(int enabled) {og_browsing=enabled;}
void p2p_lobby_browse(int enabled) {stock_browsing=enabled;}
int game_directory_snapshot(struct halo_directory_game *games,int maximum) {
 assert(og_count<=maximum);memcpy(games,og,og_count*sizeof(*games));return og_count;
}
int p2p_lobby_games(struct p2p_listing *games,int maximum) {
 assert(stock_count<=maximum);memcpy(games,stock,stock_count*sizeof(*games));return stock_count;
}
int halo_directory_engine(const char *name) {
 const char *types[]={"","CTF","Slayer","Oddball","King","Race"};
 for(int i=1;i<6;i++)if(!strcmp(types[i],name))return i;return 0;
}
static int hex_value(char c) {
 if(c>='0' && c<='9')return c-'0';if(c>='a' && c<='f')return c-'a'+10;
 if(c>='A' && c<='F')return c-'A'+10;return -1;
}
static void p2p_identifier_from_hash(const byte *hash,byte *identifier) {
 memcpy(identifier,hash,6);identifier[0]=(byte)((identifier[0]&0xfc)|2);
}
/* ACTUAL INVITE PARSER */
int p2p_invite_peer_address(const char *invite,unsigned long *address) {
 assert(!strcmp(invite,requested_invite));*address=peer_address;return connected;
}
int p2p_join_invite(const char *invite) {
 byte id[6];assert(p2p_invite_identity(invite,id));strcpy(requested_invite,invite);requested++;return TRUE;
}
void platform_show_message(const char *title,const char *message) {(void)title;(void)message;errors++;}
/* ACTUAL ADAPTER */
static void set_invite(char *invite,char hash,char token) {
 strcpy(invite,P2P_INVITE_PREFIX);size_t offset=strlen(invite);
 memset(invite+offset,hash,32);memset(invite+offset+32,token,32);invite[offset+64]=0;
}
static struct p2p_listing listing(char hash) {
 struct p2p_listing game={0};set_invite(game.invite,hash,'0');
 assert(p2p_invite_identity(game.invite,game.identifier));
 strcpy(game.name,"Stock host");strcpy(game.map,"chillout");strcpy(game.gametype,"Slayer");
 game.engine_type=2;game.player_count=2;game.maximum_player_count=16;game.open=1;return game;
}
static void real_advertisement(struct network_advertised_game *ad,const byte *id,uint32_t ip) {
 memset(ad,0,sizeof(*ad));ad->valid=1;memcpy(ad->xnaddr.abEnet,id,6);ad->xnaddr.ina=ip;
 ad->unknown100=50;ad->engine_type=2;
}
int main(void) {
 struct network_game_client client={.state=2};long count;struct network_advertised_game *rows;
 strcpy(og[0].name,"OG host");strcpy(og[0].map,"bloodgulch");strcpy(og[0].gametype,"Slayer");
 set_invite(og[0].invite,'a','0');og[0].network_version=22;og[0].max_players=16;
 og[0].open=1;og[0].player_count=1;og[0].score_limit=25;og[0].lifetime_seconds=80;og_count=1;
 stock[0]=listing('a');stock[1]=listing('b');stock_count=2;
 rows=network_game_client_get_directory_games(&client,&count);
 assert(og_browsing && stock_browsing && count==2);
 assert(!wcscmp(rows[0].game_name,L"OG host") && rows[0].unknown100==25);
 assert(!wcscmp(rows[1].game_name,L"Stock host") && rows[1].unknown100==-1);
 assert(rows[1].open && rows[1].engine_type==2 && rows[1].player_count==2);
 /* Legacy OG games stay visible, explicitly closed: their wire dialect is
    the normal Halo OG app's, so this adapter must never start an invite join. */
 og[0].network_version=11;
 network_game_client_get_directory_games(&client,&count);
 assert(count==2 && !rows[0].open && !wcsncmp(rows[0].game_name,L"OG v11: ",8));
 assert(network_game_client_directory_begin_join(&rows[0]) && !requested);
 og[0].network_version=0x800B;network_game_client_get_directory_games(&client,&count);
 assert(count==2 && !rows[0].open);
 og[0].network_version=22;network_game_client_get_directory_games(&client,&count);
 /* Selecting a signed listing starts the normal invite path; no listing can
    supply keys or gameplay options directly to the original join handler. */
 assert(network_game_client_directory_begin_join(&rows[1]) && requested==1);
 assert(!strcmp(requested_invite,stock[1].invite));
 assert(!network_game_client_directory_should_post_join(&client));
 connected=1;assert(!network_game_client_directory_should_post_join(&client));
 struct network_advertised_game *ad=&client.available_games[0];
 real_advertisement(ad,stock[1].identifier,9);assert(!network_game_client_directory_should_post_join(&client));
 real_advertisement(ad,stock[0].identifier,(uint32_t)peer_address);
 assert(!network_game_client_directory_should_post_join(&client));
 real_advertisement(ad,stock[1].identifier,(uint32_t)peer_address);
 assert(network_game_client_directory_should_post_join(&client));
 assert(!network_game_client_directory_should_post_join(&client));
 assert(network_game_client_directory_take_join(&client)==ad && ad->unknown100==50);
 assert(!network_game_client_directory_take_join(&client));
 network_game_client_get_directory_games(&client,&count);assert(count==1 && rows[0].unknown100==25);
 ad->valid=0;stock[2]=stock[1];set_invite(stock[2].invite,'b','1');stock_count=3;
 network_game_client_get_directory_games(&client,&count);assert(count==2);
 /* Upstream expiry/tombstones withdraw snapshots; the adapter must clear rows. */
 og_count=stock_count=0;network_game_client_get_directory_games(&client,&count);assert(!count);
 stock[0]=listing('b');stock_count=1;
 struct p2p_listing valid=stock[0];
 for(int invalid=0;invalid<13;invalid++) {
  stock[0]=valid;
  switch(invalid) {
  case 0:stock[0].maximum_player_count=0;break;
  case 1:stock[0].maximum_player_count=129;break;
  case 2:stock[0].player_count=17;break;
  case 3:stock[0].engine_type=6;break;
  case 4:stock[0].identifier[1]^=1;break;
  case 5:memset(stock[0].name,'X',sizeof(stock[0].name));break;
  case 6:strcpy(stock[0].map,"../ui");break;
  case 7:stock[0].name[0]='\n';break;
  case 8:stock[0].open=2;break;
  case 9:memset(stock[0].invite,'X',sizeof(stock[0].invite));break;
  case 10:stock[0].identifier[0]=0;break;
  case 11:memset(stock[0].gametype,'X',sizeof(stock[0].gametype));break;
  case 12:stock[0].gametype[0]='\n';break;
  }
  network_game_client_get_directory_games(&client,&count);assert(!count);
 }
 /* Live stock listings may omit gametype; retain the row and use its engine. */
 stock[0]=valid;stock[0].gametype[0]=0;
 network_game_client_get_directory_games(&client,&count);
 assert(count==1 && rows[0].open && rows[0].engine_type==2);
 assert(!strcmp(directory_metadata[0].gametype,"Slayer"));
 stock[0].engine_type=0;
 network_game_client_get_directory_games(&client,&count);
 assert(count==1 && rows[0].engine_type==0 && !strcmp(directory_metadata[0].gametype,"Co-op"));
 stock[0]=valid;stock[0].name[0]=0;
 network_game_client_get_directory_games(&client,&count);
 assert(count==1 && rows[0].open && !wcscmp(rows[0].game_name,L"OpenCE Game"));
 stock[0].locked=1;stock[0].invite[0]=0;
 network_game_client_get_directory_games(&client,&count);
 assert(count==1 && !rows[0].open && !wcsncmp(rows[0].game_name,L"Password: ",10));
 stock[0]=valid;stock[0].engine_type=0;strcpy(stock[0].map,"a10");strcpy(stock[0].gametype,"Co-op");
 network_game_client_get_directory_games(&client,&count);assert(count==1 && rows[0].engine_type==0);
 stock[0]=valid;stock[0].locked=1;stock[0].invite[0]=0;
 network_game_client_get_directory_games(&client,&count);
 assert(count==1 && !rows[0].open && !wcsncmp(rows[0].game_name,L"Password: ",10));
 assert(network_game_client_directory_begin_join(rows) && requested==1);
 stock[0]=valid;network_game_client_get_directory_games(&client,&count);
 assert(network_game_client_directory_begin_join(rows) && requested==2);
 network_game_client_directory_cancel();assert(!og_browsing && !stock_browsing);
 assert(!network_game_client_directory_take_join(&client));
 network_game_client_get_directory_games(&client,&count);assert(count==1);
 network_game_client_get_directory_games(NULL,&count);assert(!count && !og_browsing && !stock_browsing);
 client.state=3;network_game_client_get_directory_games(&client,&count);assert(!count && !og_browsing && !stock_browsing);
 client.state=2;network_game_client_get_directory_games(&client,&count);
 assert(network_game_client_directory_begin_join(rows));milliseconds+=30001;
 assert(!network_game_client_directory_should_post_join(&client) && errors==1);
 /* Both providers can be full. The original menu allocates exactly64 remote
    row pointers; dedup/capacity may never append a65th signed row. */
 const char *hex="0123456789abcdef";
 for(int index=0;index<64;index++) {
  og[index]=og[0];set_invite(og[index].invite,'a','0');
  size_t offset=strlen(P2P_INVITE_PREFIX);
  og[index].invite[offset+2]=hex[index>>4];og[index].invite[offset+3]=hex[index&15];
  stock[index]=valid;set_invite(stock[index].invite,'b','0');
  stock[index].invite[offset+2]=hex[index>>4];stock[index].invite[offset+3]=hex[index&15];
  assert(p2p_invite_identity(stock[index].invite,stock[index].identifier));
 }
 og_count=stock_count=64;network_game_client_get_directory_games(&client,&count);
 assert(count==64);
 og_count=0;network_game_client_get_directory_games(&client,&count);assert(count==64);
 puts("PASS OG/OpenCE combined original list, identity/dedup/expiry/password and real-admission join");
 return 0;
}
'''
        fixture = fixture.replace("/* ACTUAL INVITE PARSER */", functions)
        fixture = fixture.replace("/* ACTUAL ADAPTER */", '\n#include "networking/network_directory.inc"\n')
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-opence-discovery-") as directory:
            source = Path(directory) / "discovery.c"
            executable = Path(directory) / ("discovery.exe" if sys.platform == "win32" else "discovery")
            source.write_text(fixture)
            flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
            result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                                     "-I", str(ROOT / "port/linux/src"), "-I", str(ROOT / "source"),
                                     str(source), "-o", str(executable)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
