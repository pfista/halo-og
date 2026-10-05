"""Desktop invite handoff must reach Halo OG instead of another installed fork."""
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
HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "posix.h"
#include "p2p_internal.h"

enum { HANDOFF_PORT = @HANDOFF_PORT@, LEGACY_PORT = 47315, SOCK_DGRAM = 2 };
/* Socket calls are in memory; these are the only address members they use. */
struct sockaddr_in { unsigned short sin_port; struct { unsigned long s_addr; } sin_addr; };
static struct { int handoff_socket, has_handoff_key; unsigned char handoff_key[32]; } p2p;
static unsigned char incoming[512], reply[32];
static int incoming_size, reply_size, sent, delivered, secret_available = 1;
static unsigned short listener_port;
static const char *invite = "halo-og://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";
static void handoff_readable(void);

int posix_user_secret(unsigned char *secret, int size)
{ memset(secret, 42, (size_t)size); return secret_available; }
void posix_random_bytes(void *bytes, posix_ulong size) { memset(bytes, 7, size); }
static unsigned long network_long(unsigned long value) { return value; }
static unsigned short network_short(unsigned short value) { return value; }
static void make_address(struct sockaddr_in *to, unsigned long address, unsigned short port)
{ memset(to, 0, sizeof(*to)); to->sin_addr.s_addr = address; to->sin_port = port; }
static int open_socket(int type, unsigned long address, unsigned short port, unsigned short *actual)
{ assert(type == SOCK_DGRAM && address == 0x7F000001 && !port && !actual); return 7; }
static int command_line_invite(char *text, int size)
{ assert(size > (int)strlen(invite)); strcpy(text, invite); return 1; }
static void platform_log(const char *format, ...) { (void)format; }
void p2p_invite_received(const char *text) { assert(!strcmp(text, invite)); delivered++; }
int posix_socket_close(int socket) { assert(socket == 7); return 0; }
int posix_socket_recvfrom(int socket, void *bytes, int size, int flags, void *address, int *length)
{
    assert(socket == 8 && !flags && size >= incoming_size && *length == sizeof(struct sockaddr_in));
    make_address(address, 0x7F000001, 65000);
    memcpy(bytes, incoming, (size_t)incoming_size);
    int result = incoming_size; incoming_size = 0; return result;
}
int posix_socket_sendto(int socket, const void *bytes, int size, int flags, const void *address, int length)
{
    const struct sockaddr_in *to = address;
    assert(!flags && length == sizeof(*to) && to->sin_addr.s_addr == 0x7F000001);
    if (socket == 8) {
        assert(size == 16 && to->sin_port == 65000);
        memcpy(reply, bytes, (size_t)size); reply_size = size;
    } else {
        assert(socket == 7 && to->sin_port == HANDOFF_PORT);
        assert(!memcmp(bytes, "halo-invite ", 12));
        sent++;
        if (to->sin_port == listener_port) {
            assert(size <= (int)sizeof(incoming));
            memcpy(incoming, bytes, (size_t)size); incoming_size = size;
            handoff_readable();
        }
    }
    return size;
}
int posix_socket_select(int *read, int *reads, int *write, int *writes, int *error, int *errors,
    posix_long seconds, posix_long microseconds, int infinite)
{
    assert(*read == 7 && *reads == 1 && !write && !*writes && !error && !*errors);
    assert(!seconds && microseconds == 150000 && !infinite);
    *reads = !!reply_size; return *reads;
}
int posix_socket_recv(int socket, void *bytes, int capacity, int flags)
{
    assert(socket == 7 && !flags && capacity >= reply_size);
    memcpy(bytes, reply, (size_t)reply_size);
    int result = reply_size; reply_size = 0; return result;
}

/* PRODUCTION_CRYPTO */
/* PRODUCTION_HANDOFF */

int main(int argc, char **argv)
{
    unsigned char secret[32], current[32], legacy[32], plaintext[256], sealed[256];
    assert(argc == 2 && HANDOFF_PORT != LEGACY_PORT);
    assert(posix_user_secret(secret, sizeof(secret)) && handoff_key(current));
    p2p_hmac_sha256(secret, sizeof(secret), "halo handoff", 12, legacy);
    assert(!p2p_equal(current, legacy, sizeof(current)));
    int sealed_size = p2p_seal(current, invite, (int)strlen(invite), sealed);
    assert(p2p_open(legacy, sealed, sealed_size, plaintext) < 0);
    assert(p2p_open(current, sealed, sealed_size, plaintext) == (int)strlen(invite));
    assert(!memcmp(plaintext, invite, strlen(invite)));
    listener_port = HANDOFF_PORT;
    p2p.handoff_socket = 8; p2p.has_handoff_key = 1;
    memcpy(p2p.handoff_key, current, sizeof(current));
    if (!strcmp(argv[1], "upstream-port")) listener_port = LEGACY_PORT;
    else if (!strcmp(argv[1], "upstream-key")) memcpy(p2p.handoff_key, legacy, sizeof(legacy));
    else if (!strcmp(argv[1], "no-secret")) secret_available = 0;
    else assert(!strcmp(argv[1], "halo-og"));
    int same_fork = !strcmp(argv[1], "halo-og");
    assert(p2p_hand_off_invite() == same_fork);
    assert(delivered == same_fork);
    assert(sent == (!secret_available ? 0 : same_fork ? 1 : 3));
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DesktopHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-og-handoff-")
        source = (PORT / "p2p.c").read_text()
        port = re.search(r"\bHANDOFF_PORT\s*=\s*(\d+)", source).group(1)
        crypto = "\n".join(line for line in (PORT / "p2p_crypto.c").read_text().splitlines()
                           if line != '#include "platform.h"')
        functions = "\n".join(signature + function_source(source, name) for name, signature in (
            ("handoff_key", "static int handoff_key(unsigned char *key)"),
            ("handoff_answer", "static void handoff_answer(const unsigned char *key, const unsigned char *message, unsigned char *answer)"),
            ("p2p_hand_off_invite", "int p2p_hand_off_invite(void)"),
            ("handoff_readable", "static void handoff_readable(void)"),
        ))
        fixture = Path(cls.temp.name) / "handoff.c"
        fixture.write_text(HARNESS.replace("@HANDOFF_PORT@", port)
                           .replace("/* PRODUCTION_CRYPTO */", crypto)
                           .replace("/* PRODUCTION_HANDOFF */", functions))
        cls.executable = Path(cls.temp.name) / ("handoff.exe" if sys.platform == "win32" else "handoff")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
        try:
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags, str(fixture),
                            "-I" + str(PORT), "-o", str(cls.executable)], check=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_running_upstream_cannot_consume_halo_og_invites(self):
        for mode in ("upstream-port", "upstream-key"):
            with self.subTest(mode=mode):
                subprocess.run([str(self.executable), mode], check=True)

    def test_running_halo_og_receives_the_original_invite(self):
        subprocess.run([str(self.executable), "halo-og"], check=True)

    def test_no_secret_keeps_invite_in_the_starting_process(self):
        subprocess.run([str(self.executable), "no-secret"], check=True)


if __name__ == "__main__":
    unittest.main()
