"""Production directory parser and System Link join gating, without user data."""
import ctypes
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"


class Game(ctypes.Structure):
    _fields_ = [("id", ctypes.c_char * 37), ("name", ctypes.c_char * 33),
                ("map", ctypes.c_char * 33), ("gametype", ctypes.c_char * 25),
                ("invite", ctypes.c_char * 77)] + [
        (field, ctypes.c_int) for field in ("player_count", "max_players", "network_version",
                                          "open", "in_progress", "has_teams", "lifetime_seconds",
                                          "score_limit", "oddball_variant")]


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-directory-test-")
        cls.library = Path(cls.temp.name) / ("protocol.dll" if sys.platform == "win32" else "protocol.so")
        command = ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared"]
        if sys.platform == "win32":
            command += ["-D_CRT_SECURE_NO_WARNINGS"] + [
                "-Wl,/EXPORT:" + name for name in ("halo_directory_parse_games", "halo_directory_encode",
                                                 "halo_directory_parse_lease")]
        else:
            command += ["-fPIC"]
        subprocess.run(command + [str(PORT / "directory_protocol.c"), "-o", str(cls.library)], check=True)
        cls.lib = ctypes.CDLL(str(cls.library))
        cls.lib.halo_directory_parse_games.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                                       ctypes.POINTER(Game), ctypes.c_int]
        cls.lib.halo_directory_encode.argtypes = [ctypes.POINTER(Game), ctypes.c_char_p, ctypes.c_int]
        cls.lib.halo_directory_parse_lease.argtypes = [ctypes.c_char_p, ctypes.c_int,
                                                       ctypes.c_char_p, ctypes.c_char_p]

    @classmethod
    def tearDownClass(cls):
        if sys.platform == "win32":
            # Windows keeps a loaded DLL's file locked. Release the fixture
            # library after its last call before deleting the temporary tree.
            from _ctypes import FreeLibrary
            import gc
            handle = cls.lib._handle
            cls.lib = None
            gc.collect()
            FreeLibrary(handle)
        cls.temp.cleanup()

    def listing(self, **changes):
        return dict(id="12345678-1234-1234-1234-123456789abc", name="Test host", map="downrush",
                    gametype="Slayer", invite="halo://join/" + "a" * 64,
                    player_count=1, max_players=16, network_version=22, expires_at=1090,
                    netcode="distributed", open=True, in_progress=False, has_teams=False,
                    score_limit=50, oddball_variant=False, **changes)

    def parse(self, games, capacity=64, **changes):
        document = dict(api_version=1, server_time=1000, games=games)
        document.update(changes)
        raw = json.dumps(document, ensure_ascii=False).encode()
        out = (Game * 64)()
        return self.lib.halo_directory_parse_games(raw, len(raw), out, capacity), out

    def test_expiry_server_clock_order_capacity_and_unknown_metadata(self):
        record = self.listing()
        record.update(expires_at=990)
        live = self.listing()
        live.update(expires_at=1037, map="custom map", extra={"future": [True, None, -1.5]})
        count, games = self.parse([record, live])
        self.assertEqual(count, 1)
        self.assertEqual(games[0].lifetime_seconds, 37)
        self.assertEqual(games[0].map, b"custom map")
        count, games = self.parse([self.listing()] * 100, capacity=3)
        self.assertEqual(count, 3)
        self.assertEqual(self.parse([self.listing()] * 257)[0], -1)
        self.assertEqual(self.parse([])[0], 0)

    def test_untrusted_paths_invites_counts_schema_and_unicode_names(self):
        for change in ({"map": "../stock"}, {"map": "bad/asset"}, {"map": "bad "},
                       {"invite": "https://evil.test/"}, {"player_count": 17},
                       {"invite": "halo-og-opence://join/" + "a" * 63},
                       {"invite": "halo-og-opence://join/" + "a" * 65},
                       {"max_players": 0}, {"open": "true"}, {"expires_at": -1},
                       {"score_limit": -1}, {"score_limit": 32768}, {"score_limit": True},
                       {"score_limit": 5.0}, {"oddball_variant": 1}, {"oddball_variant": "true"}):
            game = self.listing(); game.update(change)
            self.assertEqual(self.parse([game])[0], -1, change)
        game = self.listing(); game["name"] = "é" * 32
        count, out = self.parse([game])
        self.assertEqual(count, 1)
        self.assertEqual(out[0].name, b"?" * 32)
        self.assertEqual(self.parse([], api_version=2)[0], -1)
        raw = b'{"api_version":1,"server_time":1,"games":[],"games":[]}'
        self.assertEqual(self.lib.halo_directory_parse_games(raw, len(raw), (Game * 64)(), 64), -1)

    def test_host_encoding_escaping_bounds_and_lease(self):
        _, games = self.parse([self.listing()])
        game = games[0]; game.name = b'Test "host" \\'
        out = ctypes.create_string_buffer(1024)
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(game), out, len(out)), 1)
        self.assertEqual(json.loads(out.value)["name"], 'Test "host" \\')
        self.assertEqual(json.loads(out.value)["invite"], self.listing()["invite"])
        self.assertEqual(json.loads(out.value)["score_limit"], 50)
        self.assertIs(json.loads(out.value)["oddball_variant"], False)
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(game), out, 8), 0)
        game.map = b"../stock"
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(game), out, len(out)), 0)
        raw = json.dumps(dict(id=self.listing()["id"], lease_token="b" * 64, expires_at=1090)).encode()
        identifier, token = ctypes.create_string_buffer(37), ctypes.create_string_buffer(65)
        self.assertEqual(self.lib.halo_directory_parse_lease(raw, len(raw), identifier, token), 1)
        self.assertEqual(token.value, b"b" * 64)
        raw = raw.replace(b"b" * 64, b"x" * 64)
        self.assertEqual(self.lib.halo_directory_parse_lease(raw, len(raw), identifier, token), 0)

    def test_all_directory_invite_schemes_normalize_without_changing_record_abi(self):
        self.assertEqual((Game.player_count.offset, Game.oddball_variant.offset, ctypes.sizeof(Game)), (208, 240, 244))
        for prefix in ("halo://join/", "halo-og://join/", "halo-og-opence://join/", "HALO://JOIN/"):
            with self.subTest(prefix=prefix):
                record = self.listing()
                record["invite"] = prefix + "a" * 64
                count, games = self.parse([record])
                self.assertEqual(count, 1)
                self.assertEqual(games[0].invite.decode(), self.listing()["invite"])
                out = ctypes.create_string_buffer(1024)
                self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(games[0]), out, len(out)), 1)
                self.assertEqual(json.loads(out.value)["invite"], self.listing()["invite"])

    def test_real_score_zero_oddball_and_legacy_unknown_round_trip(self):
        record = self.listing()
        record.update(gametype="Oddball", score_limit=0, oddball_variant=True)
        count, games = self.parse([record])
        self.assertEqual(count, 1)
        self.assertEqual((games[0].score_limit, games[0].oddball_variant), (0, 1))
        out = ctypes.create_string_buffer(1024)
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(games[0]), out, len(out)), 1)
        encoded = json.loads(out.value)
        self.assertEqual(encoded["score_limit"], 0)
        self.assertIs(encoded["oddball_variant"], True)
        record.pop("score_limit"); record.pop("oddball_variant")
        count, games = self.parse([record])
        self.assertEqual(count, 1)
        self.assertEqual((games[0].score_limit, games[0].oddball_variant), (-1, 0))
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(games[0]), out, len(out)), 1)
        self.assertNotIn("score_limit", json.loads(out.value))
        record["score_limit"] = 32767
        count, games = self.parse([record])
        self.assertEqual((count, games[0].score_limit), (1, 32767))

    def test_real_system_link_score_rendering_keeps_zero_and_clears_unknown_units(self):
        source_text = (ROOT / "source/interface/ui_widget_game_data_input_functions.c").read_text()
        start = source_text.index("score_limit_text->parameters.text_box.text = ui_widget_realloc(")
        end = source_text.index("message_text->parameters.text_box.string_list_index = 2;", start)
        production = source_text[start:end]
        fixture = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <wchar.h>
#define TRUE 1
enum { game_engine_ctf, game_engine_slayer, game_engine_oddball, game_engine_king, game_engine_race };
enum { _multiplayer_game_text_string_captures=2, _multiplayer_game_text_string_frags,
 _multiplayer_game_text_string_minutes, _multiplayer_game_text_string_laps };
struct network_advertised_game { short score_limit, engine_type; int oddball_variant; };
struct widget_instance { struct { struct { wchar_t *text; short string_list_index; } text_box; } parameters; };
static void *ui_widget_realloc(void *pointer,int bytes,const char *file,int line) {
 (void)file; (void)line;
 /* The production allocation counts Xbox UTF-16 bytes; the fixture uses native wchar_t. */
 return realloc(pointer,(size_t)bytes/2*sizeof(wchar_t));
}
static int usnprintf(wchar_t *out,int length,const wchar_t *format,...) {
 va_list args; va_start(args,format); int result=vswprintf(out,(size_t)length,format,args); va_end(args); return result;
}
static void render(struct network_advertised_game *server,struct widget_instance *score_limit_text,
 struct widget_instance *score_limit_type_text) {
@PRODUCTION@
}
int main(void) {
 struct widget_instance text={0}, units={0}; struct network_advertised_game game={0};
 game.engine_type=game_engine_slayer; game.score_limit=50; render(&game,&text,&units);
 assert(!wcscmp(text.parameters.text_box.text,L"50") && units.parameters.text_box.string_list_index==_multiplayer_game_text_string_frags);
 game.score_limit=-1; render(&game,&text,&units);
 assert(!text.parameters.text_box.text[0] && units.parameters.text_box.string_list_index==1);
 game.score_limit=0; render(&game,&text,&units);
 assert(!wcscmp(text.parameters.text_box.text,L"0") && units.parameters.text_box.string_list_index==_multiplayer_game_text_string_frags);
 game.engine_type=game_engine_oddball; game.score_limit=12; render(&game,&text,&units);
 assert(!wcscmp(text.parameters.text_box.text,L"12") && units.parameters.text_box.string_list_index==_multiplayer_game_text_string_minutes);
 game.oddball_variant=TRUE; render(&game,&text,&units);
 assert(units.parameters.text_box.string_list_index==_multiplayer_game_text_string_frags);
 game.score_limit=-1; render(&game,&text,&units);
 assert(!text.parameters.text_box.text[0] && units.parameters.text_box.string_list_index==1);
 free(text.parameters.text_box.text);
}
'''.replace("@PRODUCTION@", production)
        source = Path(self.temp.name) / "score_rendering.c"
        binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
        source.write_text(fixture)
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
        result = subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                                 str(source), "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_system_link_join_requires_authenticated_peer_and_real_advertisement(self):
        # Use the production XDK field order, adapting only the Xbox's 32-bit
        # unsigned long to this fixture's native host ABI. A hand-written byte
        # layout previously repeated the directory's incorrect XNADDR offsets.
        xdk = (ROOT / "port/include/xdk/xdk_pdb.h").read_text()
        declarations = "\n".join(re.search(r"struct " + name + r" \{.*?\n\};", xdk, re.S)[0]
                                  for name in ("in_addr", "XNADDR"))
        declarations = declarations.replace("unsigned long", "uint32_t")
        fixture = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "game_directory.h"
#include "p2p.h"
@XNADDR_DECLARATIONS@
typedef struct XNADDR XNADDR;
_Static_assert(sizeof(XNADDR)==12, "Xbox XNADDR wire size");
_Static_assert(offsetof(XNADDR,abEnet)==2, "Xbox XNADDR identity position");
_Static_assert(offsetof(XNADDR,ina)==8, "Xbox XNADDR IPv4 position");
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE -1
#define HALO_PORT_NETWORK_VERSION 22
#define HALO_PORT_MAXIMUM_NETWORK_PLAYERS 128
#define NETWORK_PERFORMANCE_ADVERTISED_VERSION 0x8016
#define MAXIMUM_NETWORK_ADVERTISED_GAMES 9
#define NETWORK_GAME_NAME_LENGTH 16
#define NETWORK_GAME_MAP_NAME_LENGTH 32
#define _network_game_client_state_searching 2
#define _network_game_platform_xbox 0
#define csmemset memset
#define csmemcmp memcmp
#define csmemcpy memcpy
#define csstrcmp strcmp
#define csstrncpy strncpy
#define ustrncpy wcsncpy
typedef unsigned short word;
typedef unsigned char byte;
struct network_advertised_game {
 struct { unsigned char data[12]; } xnaddr;
 wchar_t game_name[16]; struct { char name[32]; } map;
 short engine_type, maximum_player_count, machine_count, platform, unknown100;
 word player_count; boolean open, has_teams, valid, oddball_variant; unsigned long update_time;
};
struct network_game_client { int state; struct network_advertised_game available_games[9]; };
static struct halo_directory_game cached[64];
static int cached_count, browsing, connected, requested, errors;
static unsigned long milliseconds=100, peer_address=0x1020304;
static unsigned long system_milliseconds(void) { return milliseconds; }
static void network_event(const char *s) { (void)s; }
static int network_game_client_advertised_game_is_valid(struct network_advertised_game *g) { return g->valid; }
void game_directory_browse(int enabled) { browsing=enabled; }
void p2p_lobby_browse(int enabled) { (void)enabled; }
int p2p_lobby_games(struct p2p_listing *games,int count) { (void)games; (void)count; return 0; }
int game_directory_snapshot(struct halo_directory_game *g,int cap) { assert(cap>=cached_count); memcpy(g,cached,sizeof(*g)*cached_count); return cached_count; }
int p2p_invite_identity(const char *text,unsigned char *out) {
 if(strlen(text)!=76) return 0;
 for(int i=0;i<6;i++) { unsigned value; assert(sscanf(text+12+2*i,"%2x",&value)==1); out[i]=(unsigned char)value; }
 out[0]=(unsigned char)((out[0]&0xFC)|0x02); return 1;
}
int p2p_invite_peer_address(const char *text,unsigned long *out) { (void)text; *out=peer_address; return connected; }
int p2p_join_invite(const char *text) { assert(strlen(text)==76); requested++; return 1; }
void platform_show_message(const char *a,const char *b) { (void)a;(void)b;errors++; }
'''.replace("@XNADDR_DECLARATIONS@", declarations)
        fixture += '\n#include "' + str(ROOT / "source/networking/network_directory.inc") + '"\n'
        fixture += r'''
int main(void) {
 struct network_game_client client={0}; long count; XNADDR address={0}; unsigned char identity[6];
 client.state=2; cached_count=1;
 strcpy(cached[0].name,"Host"); strcpy(cached[0].map,"downrush"); strcpy(cached[0].gametype,"Slayer");
 strcpy(cached[0].invite,"halo://join/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
 cached[0].network_version=22;cached[0].open=1;cached[0].player_count=1;cached[0].max_players=16;
 cached[0].score_limit=50;
 assert(p2p_invite_identity(cached[0].invite,identity));
 struct network_advertised_game *games=network_game_client_get_directory_games(&client,&count);
 assert(browsing && count==1 && games[0].open && games[0].unknown100==50 && !games[0].oddball_variant);
 cached[0].score_limit=-1; network_game_client_get_directory_games(&client,&count); assert(count==1 && games[0].unknown100==-1);
 cached[0].score_limit=0; network_game_client_get_directory_games(&client,&count); assert(count==1 && games[0].unknown100==0);
 cached[0].score_limit=12; cached[0].oddball_variant=1; strcpy(cached[0].gametype,"Oddball");
 network_game_client_get_directory_games(&client,&count); assert(count==1 && games[0].unknown100==12 && games[0].oddball_variant);
 cached[0].score_limit=50; cached[0].oddball_variant=0; strcpy(cached[0].gametype,"Slayer");
 network_game_client_get_directory_games(&client,&count);
 assert(network_game_client_directory_begin_join(games) && requested==1);
 assert(!network_game_client_directory_should_post_join(&client));
 connected=1; assert(!network_game_client_directory_should_post_join(&client));
 struct network_advertised_game *ad=&client.available_games[0]; ad->valid=1;
 address.bSizeOfStruct=sizeof(address); address.bFlags=0xA5;
 memcpy(address.abEnet,identity,6); address.ina.S_un.S_addr=9; memcpy(ad->xnaddr.data,&address,sizeof(address));
 assert(!network_game_client_directory_should_post_join(&client));
 address.ina.S_un.S_addr=(uint32_t)peer_address; memset(address.abEnet,0xBB,6); memcpy(ad->xnaddr.data,&address,sizeof(address));
 assert(!network_game_client_directory_should_post_join(&client));
 memcpy(address.abEnet,identity,6); memcpy(ad->xnaddr.data,&address,sizeof(address));
 assert(network_game_client_directory_should_post_join(&client));
 assert(!network_game_client_directory_should_post_join(&client));
 assert(network_game_client_directory_take_join(&client)==ad);
 assert(!network_game_client_directory_take_join(&client));
 ad->unknown100=50; /* The real advertisement supplies the Xbox score limit. */
 address.ina.S_un.S_addr=0xC0A80102; memcpy(ad->xnaddr.data,&address,sizeof(address));
 network_game_client_get_directory_games(&client,&count); assert(count==0 && ad->unknown100==50); /* LAN dedup, preserving real rules */
 cached[1]=cached[0]; memset(cached[1].invite+44,'b',32); cached_count=2;
 network_game_client_get_directory_games(&client,&count); assert(count==0); /* same identity despite renewed invite token */
 ad->valid=0; network_game_client_get_directory_games(&client,&count); assert(count==1);
 memset(cached[1].invite+12,'c',64); network_game_client_get_directory_games(&client,&count); assert(count==2); /* distinct host remains visible */
 cached_count=1;
 {
  struct halo_directory_game original=cached[0], older=original, newer=original;
  strcpy(older.name,"Old host"); older.lifetime_seconds=20; older.score_limit=10; older.player_count=12;
  strcpy(newer.name,"Fresh host"); newer.lifetime_seconds=80; newer.score_limit=25; newer.oddball_variant=1; newer.player_count=1;
  strcpy(newer.gametype,"Oddball"); memset(newer.invite+44,'b',32);
  cached[0]=older; cached[1]=newer; cached_count=2;
  network_game_client_get_directory_games(&client,&count);
  assert(count==1 && !wcscmp(games[0].game_name,L"Fresh host") && games[0].unknown100==25 && games[0].oddball_variant && games[0].player_count==1);
  assert(!strcmp(directory_metadata[0].invite,newer.invite));
  cached[0]=newer; cached[1]=older;
  network_game_client_get_directory_games(&client,&count);
  assert(count==1 && !wcscmp(games[0].game_name,L"Fresh host") && games[0].unknown100==25 && games[0].oddball_variant && games[0].player_count==1);
  assert(!strcmp(directory_metadata[0].invite,newer.invite));
  ad->valid=1; network_game_client_get_directory_games(&client,&count); assert(count==0 && ad->unknown100==50);
  ad->valid=0; cached[0]=original; cached_count=1;
  network_game_client_get_directory_games(&client,&count); assert(count==1);
 }
 assert(!network_game_client_directory_begin_join(ad)); /* original LAN flow */
 assert(network_game_client_directory_begin_join(games)); network_game_client_directory_cancel();
 assert(!browsing && !network_game_client_directory_take_join(&client)); /* stale queued event */
 network_game_client_get_directory_games(&client,&count); network_game_client_directory_begin_join(games);
 milliseconds+=30001; assert(!network_game_client_directory_should_post_join(&client) && errors==1);
 cached[0].network_version=21; network_game_client_get_directory_games(&client,&count); assert(count==0);
 cached[0].network_version=0x8016; network_game_client_get_directory_games(&client,&count); assert(count==1);
 strcpy(cached[0].gametype,"Unknown"); network_game_client_get_directory_games(&client,&count); assert(count==0);
 puts("PASS directory System Link display, dedup, peer identity, real-ad join, timeout, cancellation");
}
'''
        source = Path(self.temp.name) / "join.c"
        binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
        source.write_text(fixture)
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else ["-fsanitize=address,undefined"]
        result = subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                                 "-I", str(PORT), str(source), str(PORT / "directory_protocol.c"),
                                 "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
