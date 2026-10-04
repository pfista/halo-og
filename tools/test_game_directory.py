"""Production directory parser and System Link join gating, without user data."""
import ctypes
import json
from pathlib import Path
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
                                          "open", "in_progress", "has_teams", "lifetime_seconds")]


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
        cls.temp.cleanup()

    def listing(self, **changes):
        return dict(id="12345678-1234-1234-1234-123456789abc", name="Test host", map="downrush",
                    gametype="Slayer", invite="halo://join/" + "a" * 64,
                    player_count=1, max_players=16, network_version=11, expires_at=1090,
                    netcode="distributed", open=True, in_progress=False, has_teams=False, **changes)

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
                       {"max_players": 0}, {"open": "true"}, {"expires_at": -1}):
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
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(game), out, 8), 0)
        game.map = b"../stock"
        self.assertEqual(self.lib.halo_directory_encode(ctypes.byref(game), out, len(out)), 0)
        raw = json.dumps(dict(id=self.listing()["id"], lease_token="b" * 64, expires_at=1090)).encode()
        identifier, token = ctypes.create_string_buffer(37), ctypes.create_string_buffer(65)
        self.assertEqual(self.lib.halo_directory_parse_lease(raw, len(raw), identifier, token), 1)
        self.assertEqual(token.value, b"b" * 64)
        raw = raw.replace(b"b" * 64, b"x" * 64)
        self.assertEqual(self.lib.halo_directory_parse_lease(raw, len(raw), identifier, token), 0)

    def test_real_system_link_join_requires_authenticated_peer_and_real_advertisement(self):
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "game_directory.h"
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE -1
#define HALO_PORT_NETWORK_VERSION 11
#define NETWORK_PERFORMANCE_ADVERTISED_VERSION 0x800B
#define MAXIMUM_NETWORK_ADVERTISED_GAMES 9
#define NETWORK_GAME_NAME_LENGTH 16
#define NETWORK_GAME_MAP_NAME_LENGTH 32
#define _network_game_client_state_searching 2
#define _network_game_platform_xbox 0
#define csmemset memset
#define csmemcmp memcmp
#define csstrcmp strcmp
#define csstrncpy strncpy
#define ustrncpy wcsncpy
typedef unsigned short word;
struct network_advertised_game {
 struct { unsigned char data[12]; } xnaddr;
 wchar_t game_name[16]; struct { char name[32]; } map;
 short engine_type, maximum_player_count, machine_count, platform;
 word player_count; boolean open, has_teams, valid; unsigned long update_time;
};
struct network_game_client { int state; struct network_advertised_game available_games[9]; };
static struct halo_directory_game cached[64];
static int cached_count, browsing, connected, requested, errors;
static unsigned long milliseconds=100, peer_address=0x1020304;
static unsigned long system_milliseconds(void) { return milliseconds; }
static void network_event(const char *s) { (void)s; }
static int network_game_client_advertised_game_is_valid(struct network_advertised_game *g) { return g->valid; }
void game_directory_browse(int enabled) { browsing=enabled; }
int game_directory_snapshot(struct halo_directory_game *g,int cap) { assert(cap>=cached_count); memcpy(g,cached,sizeof(*g)*cached_count); return cached_count; }
int p2p_invite_identity(const char *text,unsigned char *out) { if(strlen(text)!=76) return 0; memset(out,text[12],6); return 1; }
int p2p_invite_peer_address(const char *text,unsigned long *out) { (void)text; *out=peer_address; return connected; }
int p2p_join_invite(const char *text) { assert(strlen(text)==76); requested++; return 1; }
void platform_show_message(const char *a,const char *b) { (void)a;(void)b;errors++; }
'''
        fixture += '\n#include "' + str(ROOT / "source/networking/network_directory.inc") + '"\n'
        fixture += r'''
int main(void) {
 struct network_game_client client={0}; long count;
 client.state=2; cached_count=1;
 strcpy(cached[0].name,"Host"); strcpy(cached[0].map,"downrush"); strcpy(cached[0].gametype,"Slayer");
 strcpy(cached[0].invite,"halo://join/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
 cached[0].network_version=11;cached[0].open=1;cached[0].player_count=1;cached[0].max_players=16;
 struct network_advertised_game *games=network_game_client_get_directory_games(&client,&count);
 assert(browsing && count==1 && games[0].open);
 assert(network_game_client_directory_begin_join(games) && requested==1);
 assert(!network_game_client_directory_should_post_join(&client));
 connected=1; assert(!network_game_client_directory_should_post_join(&client));
 struct network_advertised_game *ad=&client.available_games[0]; ad->valid=1;
 memset(ad->xnaddr.data+6,'a',6); unsigned long wrong=9; memcpy(ad->xnaddr.data,&wrong,4);
 assert(!network_game_client_directory_should_post_join(&client));
 memcpy(ad->xnaddr.data,&peer_address,4); memset(ad->xnaddr.data+6,'b',6);
 assert(!network_game_client_directory_should_post_join(&client));
 memset(ad->xnaddr.data+6,'a',6);
 assert(network_game_client_directory_should_post_join(&client));
 assert(!network_game_client_directory_should_post_join(&client));
 assert(network_game_client_directory_take_join(&client)==ad);
 assert(!network_game_client_directory_take_join(&client));
 network_game_client_get_directory_games(&client,&count); assert(count==0); /* LAN dedup */
 ad->valid=0; network_game_client_get_directory_games(&client,&count); assert(count==1);
 assert(!network_game_client_directory_begin_join(ad)); /* original LAN flow */
 assert(network_game_client_directory_begin_join(games)); network_game_client_directory_cancel();
 assert(!browsing && !network_game_client_directory_take_join(&client)); /* stale queued event */
 network_game_client_get_directory_games(&client,&count); network_game_client_directory_begin_join(games);
 milliseconds+=30001; assert(!network_game_client_directory_should_post_join(&client) && errors==1);
 cached[0].network_version=12; network_game_client_get_directory_games(&client,&count); assert(count==0);
 cached[0].network_version=0x800B; network_game_client_get_directory_games(&client,&count); assert(count==1);
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
