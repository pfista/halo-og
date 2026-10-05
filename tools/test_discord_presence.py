"""Exercise production Discord RPC presence with an isolated in-memory peer."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
APPLICATION = "1556496882329460736"
SECRET = "0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210"
HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "posix.h"
#include "port_config.h"
#include "p2p_internal.h"

static const char *application = "1556496882329460736";
static unsigned long ticks;
static int available = 1, disconnected, connections, registrations, closes;
static unsigned char input[4096], output[65536];
static int input_size, output_size;
static const char *secret = "0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";

void platform_log(const char *format, ...) { (void)format; }
const char *config_string(const char *name)
{
    assert(!strcmp(name, "discord.application_id"));
    return application;
}
unsigned long p2p_now(void) { return ticks; }
posix_ulong posix_process_id(void) { return 4321; }
const unsigned char *p2p_identifier(void)
{
    static const unsigned char identifier[P2P_IDENTIFIER_SIZE] = {2, 3, 4, 5, 6, 7};
    return identifier;
}
void p2p_hex(const unsigned char *bytes, int size, char *text)
{
    static const char digits[] = "0123456789abcdef";
    int index;
    for (index = 0; index < size; index++) {
        text[2 * index] = digits[bytes[index] >> 4];
        text[2 * index + 1] = digits[bytes[index] & 15];
    }
    text[2 * size] = 0;
}
void p2p_register_url_scheme(const char *scheme, const char *description)
{
    assert(!strcmp(scheme, "discord-1556496882329460736"));
    assert(!strcmp(description, "Halo OG"));
    registrations++;
}
void p2p_invite_received(const char *text) { (void)text; assert(0); }
int posix_discord_connect(void)
{
    connections++;
    if (!available) return -1;
    disconnected = 0;
    return 7;
}
void posix_discord_close(int handle) { assert(handle == 7); closes++; }
int posix_discord_write(int handle, const void *bytes, int size)
{
    assert(handle == 7 && size > 0);
    /* Exercise the production output queue across partial writes. */
    if (size > 7) size = 7;
    assert(output_size + size <= (int)sizeof(output));
    memcpy(output + output_size, bytes, (size_t)size);
    output_size += size;
    return size;
}
int posix_discord_read(int handle, void *bytes, int capacity)
{
    int count = input_size;
    assert(handle == 7);
    if (disconnected) return -1;
    /* The peer splits both the header and JSON across reads. */
    if (count > 5) count = 5;
    if (count > capacity) count = capacity;
    memcpy(bytes, input, (size_t)count);
    memmove(input, input + count, (size_t)(input_size - count));
    input_size -= count;
    return count;
}

/* PRODUCTION_SOURCE */

static void ready(void)
{
    const char *json = "{\"cmd\":\"DISPATCH\",\"evt\":\"READY\",\"data\":{"
        "\"user\":{\"id\":\"123456\",\"username\":\"fixture_user\"}}}";
    int size = (int)strlen(json);
    assert(!input_size && size + 8 < (int)sizeof(input));
    memset(input, 0, 8);
    input[0] = 1;
    input[4] = (unsigned char)size;
    input[5] = (unsigned char)(size >> 8);
    memcpy(input + 8, json, (size_t)size);
    input_size = size + 8;
    p2p_discord_update();
}
static void dump_frames(void)
{
    int offset = 0;
    while (offset < output_size) {
        int size;
        assert(output_size - offset >= 8);
        assert(output[offset] <= 1 && !output[offset + 1] && !output[offset + 2] && !output[offset + 3]);
        size = output[offset + 4] | output[offset + 5] << 8;
        assert(!output[offset + 6] && !output[offset + 7] && size > 0);
        assert(output_size - offset >= size + 8);
        fwrite(output + offset + 8, 1, (size_t)size, stdout);
        putchar('\n');
        offset += size + 8;
    }
}
int main(int count, char **arguments)
{
    const char *mode;
    assert(count == 2);
    mode = arguments[1];
    if (!strcmp(mode, "disabled")) {
        application = "";
        p2p_discord_update();
        ticks = 60000;
        p2p_discord_update();
        assert(!connections && !registrations && !output_size);
        return 0;
    }
    if (!strcmp(mode, "late")) {
        available = 0;
        p2p_discord_update();
        assert(connections == 1 && registrations == 1 && !output_size);
        ticks = 19999;
        p2p_discord_update();
        assert(connections == 1);
        available = 1;
        ticks = 20000;
    }
    if (!strcmp(mode, "hosting") || !strcmp(mode, "leaving") || !strcmp(mode, "reconnect"))
        p2p_discord_set_hosting(secret, 3, 16);
    p2p_discord_update();
    ready();
    assert(registrations == 1);
    if (!strcmp(mode, "leaving")) {
        p2p_discord_set_hosting(NULL, 0, 0);
        p2p_discord_update();
    }
    if (!strcmp(mode, "reconnect")) {
        ticks = 100;
        disconnected = 1;
        p2p_discord_update();
        assert(closes == 1 && connections == 1);
        /* The latest state must survive disconnect, including removal of
           the host's private party and invite. */
        p2p_discord_set_hosting(NULL, 0, 0);
        ticks = 19999;
        p2p_discord_update();
        assert(connections == 1);
        ticks = 20000;
        p2p_discord_update();
        assert(connections == 2 && registrations == 1);
        ready();
    }
    assert(connections == ((!strcmp(mode, "reconnect") || !strcmp(mode, "late")) ? 2 : 1));
    dump_frames();
    return 0;
}
'''

LIFECYCLE_HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

typedef int fixture_mutex;
typedef int fixture_thread;
#define pthread_mutex_t fixture_mutex
#define pthread_t fixture_thread
#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
#define pthread_create fixture_create
#define pthread_detach fixture_detach
enum { MAXIMUM_PROXIES = 1, MAXIMUM_LISTENERS = 1, MAXIMUM_STREAMS = 1,
    SOCK_DGRAM = 2, SOL_SOCKET = 1, SO_SNDBUF = 2, SO_RCVBUF = 3, HANDOFF_PORT = 1234 };
static struct {
    int running, tunnel_socket, handoff_socket, has_handoff_key;
    unsigned long local_address;
    unsigned short tunnel_port;
    unsigned char handoff_key[32];
    struct { int socket; } proxies[1], listeners[1], streams[1];
} p2p;
static fixture_mutex p2p_lock;
static const char *application = "1556496882329460736";
static int online, created, detached, fail_create, tunnel_opens, updates, delays, joined;
static void *(*worker)(void *);
static jmp_buf finished;
static void *discord_thread(void *unused);
static int fixture_lock(fixture_mutex *lock) { assert(!*lock); *lock = 1; return 0; }
static int fixture_unlock(fixture_mutex *lock) { assert(*lock); *lock = 0; return 0; }
static int fixture_create(fixture_thread *thread, void *attributes, void *(*start)(void *), void *data)
{
    (void)attributes; (void)data;
    assert(p2p_lock && start == discord_thread);
    if (fail_create) { fail_create = 0; return 1; }
    *thread = ++created;
    worker = start;
    return 0;
}
static int fixture_detach(fixture_thread thread) { assert(thread == created); detached++; return 0; }
static void platform_log(const char *format, ...) { (void)format; }
static const char *config_string(const char *name)
{ assert(!strcmp(name, "discord.application_id")); return application; }
static long config_integer(const char *name)
{ assert(!strcmp(name, "network.tunnel_port")); return 0; }
static int config_boolean(const char *name)
{ assert(!strcmp(name, "network.online")); return online; }
static void p2p_identifier(void) { }
static void p2p_discord_update(void) { assert(p2p_lock); updates++; }
static void SDL_Delay(unsigned delay)
{
    assert(!p2p_lock && delay == 50);
    if (++delays == 3) longjmp(finished, 1);
}
static unsigned short network_short(unsigned short value) { return value; }
static unsigned long network_long(unsigned long value) { return value; }
static int open_socket(int type, unsigned long address, unsigned short port, unsigned short *actual)
{
    (void)address; (void)port; (void)actual;
    assert(type == SOCK_DGRAM && !p2p_lock);
    tunnel_opens++;
    return -1;
}
static int posix_socket_setsockopt(int socket, int level, int name, const void *value, int size)
{ (void)socket; (void)level; (void)name; (void)value; (void)size; assert(0); return -1; }
static int handoff_key(unsigned char *key) { (void)key; assert(0); return 0; }
static void stun_setup(void) { assert(0); }
static void *p2p_thread(void *unused) { (void)unused; assert(0); return NULL; }
static void close_socket(int *socket) { (void)socket; assert(0); }
static int command_line_invite(char *invite, int size) { (void)invite; (void)size; assert(0); return 0; }
static void p2p_join_invite(const char *invite) { (void)invite; assert(0); }
static int join_invite(const char *invite) { (void)invite; joined++; return 1; }

/* PRODUCTION_LIFECYCLE */

int main(int count, char **arguments)
{
    const char *mode;
    assert(count == 2);
    mode = arguments[1];
    if (!strcmp(mode, "disabled")) application = "";
    if (!strcmp(mode, "tunnel")) online = 1;
    if (!strcmp(mode, "createfail")) fail_create = 1;
    p2p_initialize(0x7f000001);
    if (!strcmp(mode, "createfail")) assert(!created && !detached && !worker);
    p2p_initialize(0x7f000001);
    p2p_initialize(0x7f000001);
    assert(!p2p_lock && !p2p.running);
    assert(tunnel_opens == (online ? 3 : 0));
    /* Local RPC never enables Internet invites as a side effect. */
    p2p_invite_received("fixture invite");
    assert(!joined);
    p2p.running = 1;
    p2p_invite_received("fixture invite");
    assert(joined == 1);
    if (!strcmp(mode, "disabled")) {
        assert(!created && !detached && !worker && !updates);
    } else {
        assert(created == 1 && detached == 1 && worker);
        if (!setjmp(finished)) worker(NULL);
        assert(updates == 3 && delays == 3 && !p2p_lock);
    }
    return 0;
}
'''

REGISTRATION_HARNESS = r'''
#include <assert.h>
#include <pthread.h>
#include <string.h>

static pthread_mutex_t p2p_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t observation_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static _Thread_local int owns_p2p, owns_registration;
static int registration_attempts, registrations, registering, automated;

/* Wrap real mutexes to check ownership and lock order on each worker. */
static int fixture_lock(pthread_mutex_t *lock)
{
    if (lock == &p2p_lock) {
        assert(!owns_p2p && !owns_registration);
        assert(pthread_mutex_lock(lock) == 0);
        owns_p2p = 1;
    } else {
        assert(!owns_p2p && !owns_registration);
        assert(pthread_mutex_lock(&observation_lock) == 0);
        registration_attempts++;
        assert(pthread_cond_broadcast(&changed) == 0);
        assert(pthread_mutex_unlock(&observation_lock) == 0);
        assert(pthread_mutex_lock(lock) == 0);
        owns_registration = 1;
    }
    return 0;
}
static int fixture_unlock(pthread_mutex_t *lock)
{
    if (lock == &p2p_lock) {
        assert(owns_p2p && !owns_registration);
        owns_p2p = 0;
    } else {
        assert(owns_registration && !owns_p2p);
        owns_registration = 0;
    }
    return pthread_mutex_unlock(lock);
}
static double config_real(const char *name)
{ assert(!strcmp(name, "debug.exit_after")); return automated ? 1.0 : 0.0; }
static int config_boolean(const char *name)
{
    assert(!strcmp(name, "debug.hidden_window") || !strcmp(name, "debug.null_renderer"));
    return 0;
}
static int posix_register_url_scheme(const char *scheme, const char *description)
{
    assert(scheme && !strcmp(description, "Halo OG"));
    assert(!owns_p2p && owns_registration);
    assert(pthread_mutex_lock(&observation_lock) == 0);
    assert(!registering);
    registering = 1;
    /* Force the other worker to contend for the registration mutex while
       this OS operation waits. No scheduling sleeps or live OS writes. */
    while (registration_attempts < 2)
        assert(pthread_cond_wait(&changed, &observation_lock) == 0);
    registrations++;
    registering = 0;
    assert(pthread_mutex_unlock(&observation_lock) == 0);
    return 1;
}

#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
/* PRODUCTION_REGISTRATION */

static void *register_worker(void *argument)
{
    assert(pthread_mutex_lock(&p2p_lock) == 0);
    p2p_register_url_scheme(argument, "Halo OG");
    /* The production helper restores its caller's lock before returning. */
    assert(owns_p2p && !owns_registration);
    assert(pthread_mutex_unlock(&p2p_lock) == 0);
    return NULL;
}
int main(int count, char **arguments)
{
    pthread_t first, second;
    assert(count == 2);
    if (!strcmp(arguments[1], "automated")) {
        automated = 1;
        register_worker("halo");
        assert(!registrations && !registration_attempts);
    } else {
        assert(pthread_create(&first, NULL, register_worker, "halo") == 0);
        assert(pthread_create(&second, NULL, register_worker, "discord-1556496882329460736") == 0);
        assert(pthread_join(first, NULL) == 0);
        assert(pthread_join(second, NULL) == 0);
        assert(registrations == 2 && registration_attempts == 2 && !registering);
    }
    assert(!owns_p2p && !owns_registration);
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DiscordPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-discord-presence-")
        root = Path(cls.temp.name)
        # Only platform includes are replaced. The production protocol,
        # buffers, state transitions, retries and presence code are unchanged.
        production = "\n".join(line for line in (PORT / "p2p_discord.c").read_text().splitlines()
                               if not line.startswith("#include "))
        fixture = root / "presence.c"
        fixture.write_text(HARNESS.replace("/* PRODUCTION_SOURCE */", production))
        cls.executable = root / ("presence-test.exe" if sys.platform == "win32" else "presence-test")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
        try:
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                            "-I", str(PORT), str(fixture), "-o", str(cls.executable)], check=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, mode):
        result = subprocess.run([str(self.executable), mode], check=True, timeout=10,
                                text=True, capture_output=True)
        frames = [json.loads(line) for line in result.stdout.splitlines()]
        for frame in frames:
            if frame.get("cmd") == "SET_ACTIVITY":
                self.assertEqual(frame["args"]["pid"], 4321)
        return frames

    def assert_playing(self, frame, hosting=False):
        activity = frame["args"]["activity"]
        self.assertEqual(activity["type"], 0)
        self.assertEqual(activity["assets"]["large_text"], "Halo OG")
        if hosting:
            self.assertEqual(activity["details"], "Hosting a game")
            self.assertEqual(activity["state"], "Invite only")
            self.assertEqual(activity["party"], {"id": "020304050607", "size": [3, 16]})
            self.assertEqual(activity["secrets"], {"join": SECRET})
        else:
            self.assertEqual(activity["details"], "Halo OG")
            self.assertNotIn("party", activity)
            self.assertNotIn("secrets", activity)

    def activities(self, frames):
        return [frame for frame in frames if frame.get("cmd") == "SET_ACTIVITY"]

    def test_nonhost_publishes_playing_activity(self):
        frames = self.run_fixture("playing")
        self.assertEqual(frames[0], {"v": 1, "client_id": APPLICATION})
        self.assertEqual(frames[1]["cmd"], "SUBSCRIBE")
        self.assertEqual(frames[1]["evt"], "ACTIVITY_JOIN")
        self.assertEqual(len(frames), 3)
        self.assert_playing(frames[2])

    def test_host_retains_private_party_and_invite(self):
        activities = self.activities(self.run_fixture("hosting"))
        self.assertEqual(len(activities), 1)
        self.assert_playing(activities[0], hosting=True)

    def test_leaving_host_removes_invite_but_keeps_playing(self):
        activities = self.activities(self.run_fixture("leaving"))
        self.assertEqual(len(activities), 2)
        self.assert_playing(activities[0], hosting=True)
        self.assert_playing(activities[1])

    def test_reconnect_obeys_retry_interval_and_publishes_latest_state(self):
        frames = self.run_fixture("reconnect")
        self.assertEqual(sum(frame.get("v") == 1 for frame in frames), 2)
        self.assertEqual(sum(frame.get("cmd") == "SUBSCRIBE" for frame in frames), 2)
        activities = self.activities(frames)
        self.assertEqual(len(activities), 2)
        self.assert_playing(activities[0], hosting=True)
        self.assert_playing(activities[1])

    def test_discord_starting_later_retries_and_publishes_activity(self):
        activities = self.activities(self.run_fixture("late"))
        self.assertEqual(len(activities), 1)
        self.assert_playing(activities[0])

    def test_empty_application_disables_connection_and_registration(self):
        self.assertEqual(self.run_fixture("disabled"), [])


def function_source(source, name):
    """Return one C function body for small lifecycle topology checks."""
    match = re.search(r"\b" + re.escape(name) + r"\s*\([^;{}]*\)\s*\{", source)
    if not match:
        raise AssertionError(f"Function {name} was not found")
    start = match.end() - 1
    depth = 1
    position = start + 1
    # Strip comments/strings for brace matching while retaining source indices.
    tokens = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    masked = tokens.sub(lambda item: " " * len(item.group()), source)
    while depth and position < len(source):
        if masked[position] == "{":
            depth += 1
        elif masked[position] == "}":
            depth -= 1
        position += 1
    if depth:
        raise AssertionError(f"Function {name} has no closing brace")
    return source[start:position]


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DiscordLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-discord-lifecycle-")
        root = Path(cls.temp.name)
        source = (PORT / "p2p.c").read_text()
        # Compile the real worker, startup and invite callback unchanged;
        # substitute only the thread, clock and networking dependencies.
        production = "\n".join([
            "static void *discord_thread(void *unused)" + function_source(source, "discord_thread"),
            "void p2p_initialize(unsigned long local_address)" + function_source(source, "p2p_initialize"),
            "void p2p_invite_received(const char *text)" + function_source(source, "p2p_invite_received"),
        ])
        fixture = root / "lifecycle.c"
        fixture.write_text(LIFECYCLE_HARNESS.replace("/* PRODUCTION_LIFECYCLE */", production))
        cls.executable = root / ("lifecycle-test.exe" if sys.platform == "win32" else "lifecycle-test")
        try:
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(fixture), "-o", str(cls.executable)], check=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, mode):
        subprocess.run([str(self.executable), mode], check=True, timeout=10)

    def test_offline_play_starts_one_worker_and_ignores_internet_invites(self):
        self.run_fixture("offline")

    def test_tunnel_failure_keeps_local_presence_running(self):
        self.run_fixture("tunnel")

    def test_empty_application_does_not_create_worker(self):
        self.run_fixture("disabled")

    def test_failed_thread_start_can_retry(self):
        self.run_fixture("createfail")

    def test_internet_worker_does_not_also_service_local_rpc(self):
        source = (PORT / "p2p.c").read_text()
        self.assertNotIn("p2p_discord_update", function_source(source, "p2p_thread"))


@unittest.skipUnless(shutil.which("clang") and sys.platform != "win32", "clang and POSIX pthreads required")
class DiscordRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-discord-registration-")
        root = Path(cls.temp.name)
        source = (PORT / "p2p.c").read_text()
        production = ("void p2p_register_url_scheme(const char *scheme, const char *description)"
                      + function_source(source, "p2p_register_url_scheme"))
        fixture = root / "registration.c"
        fixture.write_text(REGISTRATION_HARNESS.replace("/* PRODUCTION_REGISTRATION */", production))
        cls.executable = root / "registration-test"
        try:
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pthread",
                            str(fixture), "-o", str(cls.executable)], check=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_workers_serialize_registration_without_holding_p2p_lock(self):
        subprocess.run([str(self.executable), "concurrent"], check=True, timeout=10)

    def test_automated_runs_preserve_lock_and_skip_registration(self):
        subprocess.run([str(self.executable), "automated"], check=True, timeout=10)


@unittest.skipUnless(shutil.which("clang") and sys.platform != "win32", "clang and POSIX config fixture required")
class DiscordConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.test_game_settings import CONFIG_HARNESS, PREFIX, SDL
        if not (SDL / "include/SDL3/SDL.h").exists():
            raise unittest.SkipTest("Existing real-config fixture requires SDL headers")
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-discord-config-")
        root = Path(cls.temp.name)
        prefix, fixture = root / "prefix.h", root / "config.c"
        prefix.write_text(PREFIX)
        fixture.write_text(CONFIG_HARNESS.partition("int main(")[0] + r'''
int main(void) {
    puts(config_string("discord.application_id"));
    return 0;
}
''')
        cls.executable = root / "config-test"
        try:
            subprocess.run(["clang", "-std=gnu11", "-Werror", "-pthread", "-include", str(prefix),
                            "-I" + str(PORT), "-I" + str(SDL / "include"),
                            "-I" + str(ROOT / "port/third_party/tomlc17"), str(fixture),
                            str(PORT / "port_config.c"), str(ROOT / "port/third_party/tomlc17/tomlc17.c"),
                            "-o", str(cls.executable)], check=True, capture_output=True, text=True)
        except Exception:
            cls.temp.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.saves = tempfile.TemporaryDirectory(prefix="halo-discord-config-saves-")
        self.addCleanup(self.saves.cleanup)
        self.config = Path(self.saves.name) / "config.toml"
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
        self.environment.update(HALO_SAVE_ROOT=self.saves.name, HALO_DATA_ROOT=self.saves.name)

    def read(self, override=None):
        environment = self.environment.copy()
        if override is not None:
            environment["HALO_DISCORD_APPLICATION"] = override
        result = subprocess.run([str(self.executable)], env=environment, check=True,
                                capture_output=True, text=True, timeout=10)
        return result.stdout.rstrip("\n")

    def save_application(self, application):
        self.assertEqual(self.read(), APPLICATION)
        text = self.config.read_text().replace(
            f'application_id = "{APPLICATION}"', f'application_id = "{application}"')
        text = text.replace("vsync = true", "vsync = false # preserve my display choice")
        self.config.write_text(text)
        return self.config.read_bytes()

    def test_new_config_uses_halo_og_application(self):
        self.assertEqual(self.read(), APPLICATION)
        self.assertEqual(tomllib.loads(self.config.read_text())["discord"]["application_id"], APPLICATION)

    def test_previous_bundled_application_migrates_without_rewriting_settings(self):
        before = self.save_application("1553978809840050229")
        self.assertEqual(self.read(), APPLICATION)
        self.assertEqual(self.config.read_bytes(), before)

    def test_custom_and_disabled_choices_are_preserved(self):
        for application in ("123456789012345678", ""):
            with self.subTest(application=application):
                self.config.unlink(missing_ok=True)
                before = self.save_application(application)
                self.assertEqual(self.read(), application)
                self.assertEqual(self.config.read_bytes(), before)

    def test_environment_override_wins_over_migrated_saved_application(self):
        before = self.save_application("1553978809840050229")
        for override in ("987654321098765432", "1553978809840050229", ""):
            with self.subTest(override=override):
                self.assertEqual(self.read(override), override)
                self.assertEqual(self.config.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
