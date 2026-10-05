"""Run the production directory worker with synthetic clocks and offline HTTP."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "game_directory.h"
/* All callbacks run on one fixture thread. The real worker's mutex calls
   still enforce that HTTP and delay never run while its data is locked. */
typedef int fixture_mutex;
typedef int fixture_thread;
#define pthread_mutex_t fixture_mutex
#define pthread_t fixture_thread
#define PTHREAD_MUTEX_INITIALIZER 0
#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
#define pthread_create fixture_create
#define pthread_detach fixture_detach
static int fixture_lock(fixture_mutex *lock) { assert(!*lock); *lock = 1; return 0; }
static int fixture_unlock(fixture_mutex *lock) { assert(*lock); *lock = 0; return 0; }
static int fixture_create(fixture_thread *thread, void *attributes, void *(*start)(void *), void *data)
{ (void)thread; (void)attributes; (void)start; (void)data; assert(0); return 1; }
static int fixture_detach(fixture_thread thread) { (void)thread; return 0; }
static unsigned long ticks;
static const char *mode;
static char invite_a[77], invite_b[77];
static jmp_buf finished;
static unsigned event_count, posts;
struct event { unsigned long at; const char *method; int status, size; };
static const struct event *events;
static unsigned expected_count;
static int config_boolean(const char *key) { (void)key; return 1; }
static const char *config_string(const char *key) { (void)key; return "https://directory.invalid"; }
static unsigned long p2p_now(void) { return ticks; }
static void platform_log(const char *format, ...) { (void)format; }
static void SDL_Delay(unsigned delay);

/* PRODUCTION_SOURCE */

static void publish(int enabled)
{
    game_directory_publish("Offline host", "downrush", 2, 1, 16, 11, 1, 0, 0, 50, 0, enabled);
}
int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status)
{
    const struct event *event;
    assert(!directory_lock && event_count < expected_count);
    event = &events[event_count++];
    if (ticks != event->at || strcmp(method, event->method)) {
        fprintf(stderr, "%s: request %u was %s at %lu, expected %s at %lu\n",
            mode, event_count, method, ticks, event->method, event->at);
        abort();
    }
    assert(!strncmp(url, "https://directory.invalid/v1/games", strlen("https://directory.invalid/v1/games")));
    assert(capacity >= 4096);
    *status = event->status;
    if (!strcmp(method, "POST")) {
        assert(!lease[0] && body);
        assert(strstr(body, posts ? invite_b : invite_a));
        assert(strstr(body, "\"score_limit\":50") && strstr(body, "\"oddball_variant\":false"));
        posts++;
    } else if (!strcmp(method, "PUT") || !strcmp(method, "DELETE")) {
        assert(strlen(lease) == 64 && strstr(url, "/12345678-1234-1234-1234-123456789abc"));
        assert(strcmp(method, "PUT") || (body && strstr(body, invite_a) &&
            strstr(body, "\"score_limit\":50") && strstr(body, "\"oddball_variant\":false")));
    }
    if (event->size < 0) return -1;
    if (!strcmp(method, "POST") && *status == 201) {
        int size = snprintf(response, (unsigned)capacity,
            "{\"id\":\"12345678-1234-1234-1234-123456789abc\",\"lease_token\":\"%064d\"}", 0);
        assert(size > 0 && size < capacity);
        return size;
    }
    if (!strcmp(method, "GET")) {
        const char *empty = "{\"api_version\":1,\"server_time\":0,\"games\":[]}";
        strcpy(response, empty); return (int)strlen(empty);
    }
    response[0] = 0;
    return event->size;
}
static void SDL_Delay(unsigned delay)
{
    assert(!directory_lock && delay == 200);
    ticks += delay;
    if (ticks == 200) {
        if (!strcmp(mode, "resume") || !strcmp(mode, "retry") || !strcmp(mode, "browse")) publish(0);
        else if (strcmp(mode, "renewed")) game_directory_set_invite(invite_b);
    }
    if (!strcmp(mode, "resume") && ticks == 400) publish(1);
    if (!strcmp(mode, "renewed") && ticks == 30200) game_directory_set_invite(invite_b);
    if ((!strcmp(mode, "resume") && ticks == 600) ||
        ((!strcmp(mode, "retry") || !strcmp(mode, "browse")) && ticks == 5400) ||
        (!strcmp(mode, "changed") && ticks == 5400) ||
        (!strcmp(mode, "expired") && ticks == 90200) ||
        (!strcmp(mode, "renewed") && ticks == 120200) ||
        (!strcmp(mode, "absent") && ticks == 400)) longjmp(finished, 1);
}
int main(int count, char **arguments)
{
    static const struct event resume[] = {{0,"POST",201,0},{200,"DELETE",0,-1},{400,"PUT",200,0}};
    static const struct event retry[] = {{0,"POST",201,0},{200,"DELETE",503,0},{5200,"DELETE",204,0}};
    static const struct event browse[] = {{0,"POST",201,0},{0,"GET",200,0},
        {200,"DELETE",0,-1},{5000,"GET",200,0},{5200,"DELETE",204,0}};
    static const struct event changed[] = {{0,"POST",201,0},{200,"DELETE",0,-1},
        {5200,"DELETE",204,0},{5200,"POST",201,0}};
    static const struct event absent[] = {{0,"POST",201,0},{200,"DELETE",404,0},{200,"POST",201,0}};
    struct event expired[21]; unsigned index;
    assert(count == 2); mode = arguments[1];
    if (!strcmp(mode, "resume")) { events = resume; expected_count = sizeof(resume)/sizeof(*resume); }
    else if (!strcmp(mode, "retry")) { events = retry; expected_count = sizeof(retry)/sizeof(*retry); }
    else if (!strcmp(mode, "browse")) { events = browse; expected_count = sizeof(browse)/sizeof(*browse); }
    else if (!strcmp(mode, "changed")) { events = changed; expected_count = sizeof(changed)/sizeof(*changed); }
    else if (!strcmp(mode, "absent")) { events = absent; expected_count = sizeof(absent)/sizeof(*absent); }
    else if (!strcmp(mode, "renewed")) {
        expired[0] = (struct event){0,"POST",201,0};
        expired[1] = (struct event){30000,"PUT",0,-1};
        for (index = 0; index < 18; index++) expired[index+2] = (struct event){30200+5000*index,"DELETE",0,-1};
        expired[20] = (struct event){120000,"POST",201,0};
        events = expired; expected_count = 21;
    } else {
        assert(!strcmp(mode, "expired"));
        expired[0] = (struct event){0,"POST",201,0};
        for (index = 0; index < 18; index++) expired[index+1] = (struct event){200+5000*index,"DELETE",0,-1};
        expired[19] = (struct event){90000,"POST",201,0};
        events = expired; expected_count = 20;
    }
    strcpy(invite_a, "halo://join/"); memset(invite_a+12, 'a', 64); invite_a[76] = 0;
    strcpy(invite_b, "halo://join/"); memset(invite_b+12, 'b', 64); invite_b[76] = 0;
    running = 1; /* The fixture invokes the worker itself, without a real thread. */
    strcpy(directory_url, config_string("network.directory_url"));
    game_directory_set_invite(invite_a); publish(1);
    if (!strcmp(mode, "browse")) game_directory_browse(1);
    if (!setjmp(finished)) directory_worker(NULL);
    assert(event_count == expected_count);
    assert(posts == ((!strcmp(mode, "changed") || !strcmp(mode, "expired") || !strcmp(mode, "absent") ||
        !strcmp(mode, "renewed")) ? 2u : 1u));
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DirectoryWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-directory-worker-")
        root = Path(cls.temp.name)
        # Only platform includes are replaced; every production worker/API
        # statement is compiled unchanged, with the real directory parser.
        production = "\n".join(line for line in (PORT / "game_directory.c").read_text().splitlines()
                               if not line.startswith("#include "))
        fixture = root / "worker.c"
        fixture.write_text(HARNESS.replace("/* PRODUCTION_SOURCE */", production))
        cls.executable = root / ("worker-test.exe" if sys.platform == "win32" else "worker-test")
        flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
        subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                        "-Wno-unused-parameter", "-I", str(PORT), str(fixture),
                        str(PORT / "directory_protocol.c"), "-o", str(cls.executable)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, mode):
        subprocess.run([str(self.executable), mode], check=True, timeout=10)

    def test_resume_reuses_lease_after_failed_withdrawal(self):
        self.run_fixture("resume")

    def test_failed_withdrawal_retries_without_flooding(self):
        self.run_fixture("retry")

    def test_browsing_continues_during_failed_withdrawal(self):
        self.run_fixture("browse")

    def test_new_invite_waits_for_old_listing_withdrawal(self):
        self.run_fixture("changed")

    def test_expired_lease_does_not_block_new_invite(self):
        self.run_fixture("expired")

    def test_missing_listing_allows_new_invite(self):
        self.run_fixture("absent")

    def test_lost_renewal_response_preserves_possible_full_lifetime(self):
        self.run_fixture("renewed")


if __name__ == "__main__":
    unittest.main()
