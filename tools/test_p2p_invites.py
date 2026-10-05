"""Compile shared production invite functions without OS registration or networking.

The fixture uses the same parser, host link generation, command-line selection
and SDL clipboard handling compiled by the native ports. Only their external
dependencies are substituted, so this can also run in Linux and Windows CI.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_discord_presence import function_source


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
CODE = "000102030405060708090a0b0c0d0e0ff0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"
PREFIX = "halo-og://join/"
LEGACY_PREFIX = "halo://join/"
COMPILER = shutil.which("clang") or shutil.which("cc")
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "posix.h"
#include "p2p_internal.h"

typedef int BOOL;
enum { FALSE = 0, TRUE = 1 };
static int p2p_lock;
static struct {
    int running, hosting_socket, hosting, has_token, invite_copied, has_clipboard;
    int game_player_count, game_player_maximum;
    int reported_player_count, reported_player_maximum, stun_started;
    unsigned char token[P2P_TOKEN_SIZE];
    /* PRODUCTION_INVITE_BUFFERS */
} p2p;
static const char *code = "@CODE@";
static const char *link = "@PREFIX@@CODE@";
static char directory_invite[P2P_LINK_SIZE], discord_secret[P2P_INVITE_CODE_SIZE + 1];
static char os_clipboard[1024];
static int random_calls, signal_starts, signal_hosts, signal_stops;
static int directory_clears, discord_updates, joined, clipboard_writes;
static int clipboard_enabled = 1, automated;
static const char **command_arguments;
static int command_argument_count;

static void pthread_mutex_lock(int *lock) { assert(!*lock); *lock = 1; }
static void pthread_mutex_unlock(int *lock) { assert(*lock); *lock = 0; }
void platform_log(const char *format, ...) { (void)format; }
void posix_random_bytes(void *bytes, posix_ulong size)
{
    unsigned char *token = bytes;
    assert(size == P2P_TOKEN_SIZE);
    for (int index = 0; index < (int)size; index++) token[index] = (unsigned char)(0xf0 + index);
    random_calls++;
}
const unsigned char *p2p_public_key(void)
{ static unsigned char key[P2P_KEY_SIZE]; return key; }
void p2p_key_hash(const unsigned char *key, unsigned char *hash)
{
    assert(key == p2p_public_key());
    for (int index = 0; index < P2P_KEY_HASH_SIZE; index++) hash[index] = (unsigned char)index;
}
void game_directory_set_invite(const char *text)
{
    if (!text) { directory_clears++; return; }
    assert(strlen(text) + 1 <= sizeof(directory_invite));
    strcpy(directory_invite, text);
}
void p2p_signal_start(void) { signal_starts++; }
void p2p_signal_host(const unsigned char *token)
{ assert(!memcmp(token, p2p.token, P2P_TOKEN_SIZE)); signal_hosts++; }
void p2p_signal_stop_hosting(void) { signal_stops++; }
static int connected_player_count(void) { return 2; }
void p2p_discord_set_hosting(const char *secret, int count, int maximum)
{
    if (secret) {
        assert(strlen(secret) == P2P_INVITE_CODE_SIZE && !strcmp(secret, code));
        assert(count == 3 && maximum == P2P_MAXIMUM_PEERS + 1);
        strcpy(discord_secret, secret);
    } else { assert(!count && !maximum); discord_secret[0] = 0; }
    discord_updates++;
}
int posix_command_line_argument(int index, char *text, posix_ulong size)
{
    if (index >= command_argument_count) return 0;
    snprintf(text, (size_t)size, "%s", command_arguments[index]);
    return 1;
}
static const char *config_string(const char *name)
{ assert(!strcmp(name, "debug.network_test")); return automated ? "fixture" : ""; }
static int config_boolean(const char *name)
{ assert(!strcmp(name, "network.join_from_clipboard")); return clipboard_enabled; }
static void SDL_SetClipboardText(const char *text)
{
    assert(strlen(text) + 1 <= sizeof(os_clipboard));
    strcpy(os_clipboard, text); clipboard_writes++;
}
static char *SDL_GetClipboardText(void) { return os_clipboard; }
static void SDL_free(void *text) { assert(text == os_clipboard); }

/* PRODUCTION_FUNCTIONS */

/* The clipboard's join boundary uses the production parser too. */
int p2p_join_invite(const char *text)
{
    unsigned char hash[P2P_KEY_HASH_SIZE], token[P2P_TOKEN_SIZE];
    int valid = parse_invite(text, hash, token) == 1;
    joined += valid;
    return valid;
}

/* PRODUCTION_CLIPBOARD */

static void verify_payload(const unsigned char *hash, const unsigned char *token)
{
    for (int index = 0; index < P2P_KEY_HASH_SIZE; index++) assert(hash[index] == index);
    for (int index = 0; index < P2P_TOKEN_SIZE; index++) assert(token[index] == 0xf0 + index);
}
int main(int argc, char **argv)
{
    assert(argc >= 2);
    if (!strcmp(argv[1], "parse")) {
        unsigned char hash[P2P_KEY_HASH_SIZE], token[P2P_TOKEN_SIZE];
        assert(argc == 4);
        memset(hash, 0x55, sizeof(hash)); memset(token, 0x55, sizeof(token));
        int expected = atoi(argv[3]);
        assert(parse_invite(argv[2], hash, token) == expected);
        if (expected == 1) verify_payload(hash, token);
        else {
            for (int index = 0; index < (int)sizeof(hash); index++) assert(hash[index] == 0x55);
            for (int index = 0; index < (int)sizeof(token); index++) assert(token[index] == 0x55);
        }
    } else if (!strcmp(argv[1], "detect")) {
        assert(argc == 4);
        assert(platform_text_has_invite_link(argv[2]) == atoi(argv[3]));
        assert(!p2p_invite_prefix_length(NULL));
    } else if (!strcmp(argv[1], "host")) {
        assert(P2P_INVITE_CODE_SIZE == 2 * (P2P_KEY_HASH_SIZE + P2P_TOKEN_SIZE));
        assert(P2P_LINK_SIZE == strlen(link) + 1);
        assert(sizeof(p2p.invite) == P2P_LINK_SIZE && sizeof(p2p.clipboard) == P2P_LINK_SIZE);
        p2p.running = 1; p2p.hosting_socket = 7;
        update_hosting();
        assert(random_calls == 1 && signal_starts == 1 && signal_hosts == 1);
        assert(!strcmp(p2p.invite, link) && !strcmp(directory_invite, link));
        assert(!strcmp(discord_secret, code) && discord_updates == 1);
        const char *copied = p2p_take_clipboard_text();
        assert(copied && !strcmp(copied, link) && !p2p_take_clipboard_text());
        unsigned char hash[P2P_KEY_HASH_SIZE], token[P2P_TOKEN_SIZE];
        assert(parse_invite(p2p.invite, hash, token) == 1); verify_payload(hash, token);
        assert(parse_invite(discord_secret, hash, token) == 1); verify_payload(hash, token);
        update_hosting();
        assert(discord_updates == 1 && random_calls == 1 && !p2p_take_clipboard_text());
        p2p.hosting_socket = -1; update_hosting();
        assert(directory_clears == 1 && signal_stops == 1 && !discord_secret[0]);
        p2p.hosting_socket = 7; update_hosting();
        assert(random_calls == 1 && signal_hosts == 2 && !strcmp(p2p.invite, link));
        assert(!strcmp(discord_secret, code) && !p2p_take_clipboard_text());
    } else if (!strcmp(argv[1], "clipboard")) {
        assert(argc == 5);
        p2p.running = 1; strcpy(os_clipboard, argv[2]);
        clipboard_enabled = atoi(argv[4]);
        platform_invite_clipboard(FALSE); assert(!joined);
        platform_invite_clipboard(TRUE); assert(joined == atoi(argv[3]));
        platform_invite_clipboard(TRUE); assert(joined == atoi(argv[3]));
        assert(!clipboard_writes && !p2p_lock);
    } else if (!strcmp(argv[1], "copy")) {
        assert(argc == 3); automated = atoi(argv[2]);
        p2p.running = 1; strcpy(p2p.clipboard, link); p2p.has_clipboard = 1;
        platform_invite_clipboard(TRUE);
        assert(clipboard_writes == !automated && !joined && !p2p.has_clipboard);
        if (!automated) assert(!strcmp(os_clipboard, link));
        platform_invite_clipboard(TRUE); assert(clipboard_writes == !automated && !joined);
    } else if (!strcmp(argv[1], "command-line")) {
        char invite[256];
        assert(argc == 5);
        const char *arguments[] = { "halo-og", "--ignored", argv[2], argv[3] };
        command_arguments = arguments; command_argument_count = 4;
        int found = command_line_invite(invite, sizeof(invite));
        assert(found == !!*argv[4]);
        if (found) assert(!strcmp(invite, argv[4]));
    } else { assert(0); }
    return 0;
}
'''


@unittest.skipUnless(COMPILER, "a C11 compiler is required")
class SharedInviteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (PORT / "p2p.c").read_text()
        clipboard = (PORT / "sdl_platform.c").read_text()
        signatures = (
            ("p2p_hex", "void p2p_hex(const unsigned char *bytes, int size, char *text)"),
            ("hex_value", "static int hex_value(char digit)"),
            ("parse_invite", "static int parse_invite(const char *text, unsigned char *host_hash, unsigned char *token)"),
            ("update_hosting", "static void update_hosting(void)"),
            ("p2p_take_clipboard_text", "const char *p2p_take_clipboard_text(void)"),
            ("command_line_invite", "static int command_line_invite(char *text, int size)"),
        )
        functions = "\n".join(signature + function_source(source, name) for name, signature in signatures)
        clipboard_functions = "\n".join(signature + function_source(clipboard, name) for name, signature in (
            ("platform_text_has_invite_link", "static BOOL platform_text_has_invite_link(const char *text)"),
            ("platform_invite_clipboard", "static void platform_invite_clipboard(BOOL look)"),
        ))
        # Preserve production buffer declarations as well as function bodies.
        # Mirrored fixture sizes would miss a link truncated by the longer scheme.
        state = re.search(r"static struct\s*\{(.*?)\}\s*p2p\s*=", source, re.S).group(1)
        buffers = "\n".join(re.findall(r"\bchar (?:invite|clipboard)\[[^\]]+\];", state))
        if len(buffers.splitlines()) != 2:
            raise AssertionError("Expected the two production invite output buffers")
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-og-invites-")
        fixture = Path(cls.temp.name) / "invites.c"
        fixture.write_text(HARNESS.replace("@CODE@", CODE).replace("@PREFIX@", PREFIX)
                           .replace("/* PRODUCTION_INVITE_BUFFERS */", buffers)
                           .replace("/* PRODUCTION_FUNCTIONS */", functions)
                           .replace("/* PRODUCTION_CLIPBOARD */", clipboard_functions))
        cls.executable = Path(cls.temp.name) / ("invites.exe" if sys.platform == "win32" else "invites")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
        try:
            subprocess.run([COMPILER, "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                            "-I", str(PORT), str(fixture), "-o", str(cls.executable)], check=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, *arguments):
        subprocess.run([str(self.executable), *map(str, arguments)], check=True, timeout=10)

    def test_new_and_legacy_uri_preserve_full_hash_and_token(self):
        for prefix in (PREFIX, LEGACY_PREFIX):
            for text in (prefix + CODE, (prefix + CODE).upper(),
                         f"Join my game: <{prefix}{CODE}>."):
                with self.subTest(text=text):
                    self.run_fixture("parse", text, 1)

    def test_discord_bare_secret_remains_64_hex_digits(self):
        for text in (CODE, CODE.upper(), " \t\r\n" + CODE + " \t\r\n"):
            with self.subTest(text=text):
                self.run_fixture("parse", text, 1)

    def test_malformed_inputs_cannot_become_an_invite(self):
        for text in ("", " ", "halo-og://join/", "halo-og://join/xyz",
                     "halo-og://other/" + CODE, "haloog://join/" + CODE,
                     "discord-123://join/" + CODE, "arbitrary " + CODE,
                     CODE + " trailing text", CODE[:31] + "z" + CODE[32:],
                     CODE + "0", CODE[:-1], PREFIX + CODE + "0", PREFIX + CODE[:-1]):
            with self.subTest(text=text):
                self.run_fixture("parse", text, 0)

    def test_older_44_digit_invites_keep_explicit_version_rejection(self):
        for prefix in (PREFIX, LEGACY_PREFIX, ""):
            with self.subTest(prefix=prefix):
                self.run_fixture("parse", prefix + CODE[:44], -1)

    def test_clipboard_prefix_detection_accepts_both_schemes_only(self):
        for prefix in (PREFIX, LEGACY_PREFIX):
            for text in (prefix + CODE, "Invite: " + prefix.upper() + CODE):
                with self.subTest(text=text):
                    self.run_fixture("detect", text, 1)
        for text in ("", CODE, "halo-og://other/" + CODE, "haloog://join/" + CODE):
            with self.subTest(text=text):
                self.run_fixture("detect", text, 0)

    def test_generated_uri_clipboard_and_discord_secret_round_trip(self):
        self.run_fixture("host")

    def test_clipboard_joins_new_and_legacy_links_once_on_focus(self):
        for prefix in (PREFIX, LEGACY_PREFIX):
            with self.subTest(prefix=prefix):
                self.run_fixture("clipboard", "Invite: " + prefix + CODE, 1, 1)

    def test_clipboard_ignores_bare_checksum_malformed_and_disabled_invites(self):
        for text in (CODE, PREFIX + CODE[:-1], PREFIX + CODE + "0", PREFIX + CODE[:44]):
            with self.subTest(text=text):
                self.run_fixture("clipboard", text, 0, 1)
        self.run_fixture("clipboard", PREFIX + CODE, 0, 0)

    def test_host_clipboard_uses_new_scheme_and_automated_runs_leave_it_alone(self):
        for automated in (0, 1):
            with self.subTest(automated=automated):
                self.run_fixture("copy", automated)

    def test_command_line_scans_for_new_legacy_or_bare_invites(self):
        for text in (PREFIX + CODE, LEGACY_PREFIX + CODE, CODE, LEGACY_PREFIX + CODE[:44]):
            with self.subTest(text=text):
                self.run_fixture("command-line", PREFIX + CODE[:-1], text, text)
        self.run_fixture("command-line", "halo-og://join/xyz", "--another-option", "")


if __name__ == "__main__":
    unittest.main()
