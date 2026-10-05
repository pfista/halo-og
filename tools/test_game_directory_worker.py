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
#include <stdint.h>
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
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds)
{
    const struct event *event;
    *retry_after_seconds = 0;
    if (!strcmp(mode, "expired") || !strcmp(mode, "renewed")) {
        assert(!directory_lock);
        if (!strcmp(method, "DELETE")) {
            assert(strlen(lease) == 64); event_count++; *status = 0; return -1;
        }
        if (!strcmp(method, "PUT")) {
            assert(!strcmp(mode, "renewed") && ticks == 30000);
            event_count++; *status = 0; return -1;
        }
        assert(!strcmp(method, "POST"));
        assert(ticks == (posts ? (!strcmp(mode, "renewed") ? 120000u : 90000u) : 0));
        posts++;
        *status = 201;
        return snprintf(response, (unsigned)capacity, "{\"id\":\"12345678-1234-1234-1234-123456789abc\",\"lease_token\":\"%064d\"}", 0);
    }
    assert(!directory_lock && event_count < expected_count);
    event = &events[event_count++];
    if (ticks < event->at || ticks > event->at + (event->at == 5200 ? 1400u : 0u) || strcmp(method, event->method)) {
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
    if (!strcmp(mode, "browse")) game_directory_browse(1);
    if (ticks == 200) {
        if (!strcmp(mode, "resume") || !strcmp(mode, "retry") || !strcmp(mode, "browse")) publish(0);
        else if (strcmp(mode, "renewed")) game_directory_set_invite(invite_b);
    }
    if (!strcmp(mode, "resume") && ticks == 400) publish(1);
    if (!strcmp(mode, "renewed") && ticks == 30200) game_directory_set_invite(invite_b);
    if ((!strcmp(mode, "resume") && ticks == 600) ||
        (!strcmp(mode, "retry") && ticks == 6800) ||
        (!strcmp(mode, "changed") && ticks == 6800) ||
        (!strcmp(mode, "browse") && ticks == 10200) ||
        (!strcmp(mode, "expired") && ticks == 90200) ||
        (!strcmp(mode, "renewed") && ticks == 120200) ||
        (!strcmp(mode, "absent") && ticks == 400)) longjmp(finished, 1);
}
int main(int count, char **arguments)
{
    static const struct event resume[] = {{0,"POST",201,0},{200,"DELETE",0,-1},{400,"PUT",200,0}};
    static const struct event retry[] = {{0,"POST",201,0},{200,"DELETE",503,0},{5200,"DELETE",204,0}};
    static const struct event browse[] = {{0,"POST",201,0},{0,"GET",200,0},
        {200,"DELETE",0,-1},{5200,"DELETE",204,0},{10000,"GET",200,0}};
    static const struct event changed[] = {{0,"POST",201,0},{200,"DELETE",0,-1},
        {5200,"DELETE",204,0},{5200,"POST",201,0}};
    static const struct event absent[] = {{0,"POST",201,0},{200,"DELETE",404,0},{200,"POST",201,0}};
    assert(count == 2); mode = arguments[1];
    if (!strcmp(mode, "resume")) { events = resume; expected_count = sizeof(resume)/sizeof(*resume); }
    else if (!strcmp(mode, "retry")) { events = retry; expected_count = sizeof(retry)/sizeof(*retry); }
    else if (!strcmp(mode, "browse")) { events = browse; expected_count = sizeof(browse)/sizeof(*browse); }
    else if (!strcmp(mode, "changed")) { events = changed; expected_count = sizeof(changed)/sizeof(*changed); }
    else if (!strcmp(mode, "absent")) { events = absent; expected_count = sizeof(absent)/sizeof(*absent); }
    else assert(!strcmp(mode, "expired") || !strcmp(mode, "renewed"));
    strcpy(invite_a, "halo://join/"); memset(invite_a+12, 'a', 64); invite_a[76] = 0;
    strcpy(invite_b, "halo://join/"); memset(invite_b+12, 'b', 64); invite_b[76] = 0;
    running = 1; /* The fixture invokes the worker itself, without a real thread. */
    strcpy(directory_url, config_string("network.directory_url"));
    game_directory_set_invite(invite_a); publish(1);
    if (!strcmp(mode, "browse")) game_directory_browse(1);
    if (!setjmp(finished)) directory_worker(NULL);
    if (!strcmp(mode, "expired") || !strcmp(mode, "renewed")) {
        assert(posts == 2 && event_count <= 6);
        return 0;
    }
    assert(event_count == expected_count);
    assert(posts == ((!strcmp(mode, "changed") || !strcmp(mode, "expired") || !strcmp(mode, "absent") ||
        !strcmp(mode, "renewed")) ? 2u : 1u));
    return 0;
}
'''


SCHEDULER = HARNESS.split("/* PRODUCTION_SOURCE */")[0] + r'''
/* PRODUCTION_SOURCE */
static unsigned long request_times[64];
static const char *request_methods[64];
static unsigned long stop_at;
static int visible = 1;
static void host_publish(int enabled)
{
    game_directory_publish("Public host", "bloodgulch", 2, 1, 16, 11, 1, 0, 0, 50, 0, enabled);
}
int halo_directory_http(const char *method, const char *url, const char *lease,
    const char *body, char *response, int capacity, int *status, int *retry_after_seconds)
{
    assert(!directory_lock && event_count < 64);
    request_times[event_count] = ticks; request_methods[event_count++] = method;
    *status = 200; *retry_after_seconds = 0;
    if (!strcmp(mode, "failure")) *status = 503;
    if (!strcmp(mode, "throttle") && event_count == 1) {
        *status = 429; *retry_after_seconds = 30;
    }
    if (!strcmp(mode, "stale") && event_count == 1) {
        game_directory_set_foreground(0); game_directory_set_foreground(1);
    }
    if (!strcmp(method, "POST")) {
        if (!strcmp(mode, "host_throttle") && event_count == 1) {
            *status = 429; *retry_after_seconds = 30; strcpy(response, "{}"); return 2;
        }
        if (!strcmp(mode, "slow_publish")) { ticks += 5000; game_directory_browse(0); visible = 0; }
        *status = 201;
        return snprintf(response, (unsigned)capacity,
            "{\"id\":\"12345678-1234-1234-1234-123456789abc\",\"lease_token\":\"%064d\"}", 0);
    }
    if (!strcmp(method, "GET")) {
        strcpy(response, "{\"api_version\":1,\"server_time\":0,\"games\":[]}");
        return (int)strlen(response);
    }
    assert(!strcmp(method, "PUT"));
    if (!strcmp(mode, "host_renew_failure") && event_count == 2) *status = 503;
    response[0] = 0; return 0;
}
static void SDL_Delay(unsigned delay)
{
    assert(!directory_lock && delay == 200); ticks += delay;
    if (!strcmp(mode, "stale") && ticks == 200) assert(cached_count == 7);
    if (!strcmp(mode, "leave") && ticks == 200) { visible = 0; game_directory_browse(0); }
    if (!strcmp(mode, "foreground")) {
        if (ticks == 200) game_directory_set_foreground(0);
        if (ticks == 12400) game_directory_set_foreground(1);
    }
    if ((!strcmp(mode, "quick") || !strcmp(mode, "throttle")) && ticks == 200) {
        game_directory_browse(0); game_directory_browse(1);
    }
    if (!strcmp(mode, "host_throttle") && ticks == 200) { host_publish(0); host_publish(1); }
    if (visible && strcmp(mode, "idle") &&
        (strcmp(mode, "visibility") || ticks >= 12000)) game_directory_browse(1);
    if (ticks >= stop_at) longjmp(finished, 1);
}
int main(int argc, char **argv)
{
    /* Shared platform fixture declarations used by the withdrawal scenarios. */
    (void)posts; (void)invite_b; (void)events; (void)expected_count;
    assert(argc == 2); mode = argv[1]; running = 1; stop_at = 35000;
    strcpy(directory_url, "https://directory.invalid");
    if (strcmp(mode, "idle")) game_directory_browse(1);
    if (!strcmp(mode, "foreground")) stop_at = 24000;
    if (!strcmp(mode, "leave")) stop_at = 30000;
    if (!strcmp(mode, "quick") || !strcmp(mode, "stale")) stop_at = 1000;
    if (!strcmp(mode, "visibility")) stop_at = 12400;
    if (!strcmp(mode, "throttle")) stop_at = 40200;
    if (!strcmp(mode, "failure")) stop_at = 180000;
    if (!strcmp(mode, "stale")) cached_count = 7;
    if (!strcmp(mode, "host_background") || !strcmp(mode, "slow_publish") ||
        !strcmp(mode, "host_throttle") || !strcmp(mode, "host_renew_failure")) {
        strcpy(invite_a, "halo://join/"); memset(invite_a + 12, 'a', 64); invite_a[76] = 0;
        game_directory_set_invite(invite_a);
        host_publish(1);
        if (strcmp(mode, "slow_publish")) game_directory_set_foreground(0);
        stop_at = !strcmp(mode, "host_throttle") || !strcmp(mode, "host_renew_failure") ? 70000 : 36000;
    }
    if (!setjmp(finished)) directory_worker(NULL);
    if (!strcmp(mode, "idle")) assert(event_count == 0);
    else if (!strcmp(mode, "leave")) assert(event_count == 1 && request_times[0] == 0);
    else if (!strcmp(mode, "foreground")) {
        assert(event_count == 3 && request_times[0] == 0 && request_times[1] == 12400 && request_times[2] == 22400);
    } else if (!strcmp(mode, "quick") || !strcmp(mode, "stale")) {
        assert(event_count == 2 && request_times[0] == 0 && request_times[1] == 200);
        if (!strcmp(mode, "stale")) assert(cached_count == 0);
    } else if (!strcmp(mode, "visibility")) {
        assert(event_count == 2 && request_times[0] == 0 && request_times[1] == 12000);
    } else if (!strcmp(mode, "throttle")) {
        assert(event_count == 3 && request_times[0] == 0 && request_times[1] == 30000 && request_times[2] == 40000);
    } else if (!strcmp(mode, "failure")) {
        assert(event_count >= 5 && event_count <= 7);
        for (unsigned i = 1; i < event_count; i++) {
            unsigned long interval = request_times[i] - request_times[i - 1];
            assert(interval >= (i == 1 ? 5000 : i == 2 ? 10000 : i == 3 ? 20000 : i == 4 ? 40000 : 60000));
            assert(interval <= 60200);
        }
    } else if (!strcmp(mode, "host_throttle")) {
        assert(event_count == 3 && !strcmp(request_methods[0], "POST") && !strcmp(request_methods[1], "POST") &&
            !strcmp(request_methods[2], "PUT"));
        assert(request_times[0] == 0 && request_times[1] == 30000 && request_times[2] == 60000);
    } else if (!strcmp(mode, "host_renew_failure")) {
        assert(event_count == 4 && !strcmp(request_methods[0], "POST"));
        assert(request_times[1] == 30000 && request_times[2] >= 35000 && request_times[2] <= 36400);
        assert(request_times[3] == request_times[2] + 30000);
        for (unsigned i = 1; i < event_count; i++) assert(!strcmp(request_methods[i], "PUT"));
    } else if (!strcmp(mode, "host_background") || !strcmp(mode, "slow_publish")) {
        assert(event_count == 2 && !strcmp(request_methods[0], "POST") && !strcmp(request_methods[1], "PUT"));
        assert(request_times[1] == (!strcmp(mode, "slow_publish") ? 35000u : 30000u));
    } else {
        assert(!strcmp(mode, "browse") && event_count == 4);
        for (unsigned i = 0; i < event_count; i++) assert(request_times[i] == i * 10000u);
    }
    return 0;
}
'''


def compile_fixture(harness, path):
    production = "\n".join(line for line in (PORT / "game_directory.c").read_text().splitlines()
                           if not line.startswith("#include "))
    fixture = path.with_suffix(".c")
    fixture.write_text(harness.replace("/* PRODUCTION_SOURCE */", production))
    flags = ["-D_CRT_SECURE_NO_WARNINGS"] if sys.platform == "win32" else []
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags,
                    "-Wno-unused-parameter", "-I", str(PORT), str(fixture),
                    str(PORT / "directory_protocol.c"), "-o", str(path)], check=True)


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DirectoryWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-directory-worker-")
        root = Path(cls.temp.name)
        # Only platform includes are replaced; every production worker/API
        # statement is compiled unchanged, with the real directory parser.
        cls.executable = root / ("worker-test.exe" if sys.platform == "win32" else "worker-test")
        compile_fixture(HARNESS, cls.executable)

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


@unittest.skipUnless(shutil.which("clang"), "clang required")
class DirectorySchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-directory-scheduler-")
        cls.executable = Path(cls.temp.name) / ("scheduler.exe" if sys.platform == "win32" else "scheduler")
        compile_fixture(SCHEDULER, cls.executable)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_fixture(self, mode):
        subprocess.run([str(self.executable), mode], check=True, timeout=10)

    def test_idle_worker_does_not_request_games(self): self.run_fixture("idle")
    def test_visible_page_refreshes_every_ten_seconds(self): self.run_fixture("browse")
    def test_leaving_page_stops_requests(self): self.run_fixture("leave")
    def test_background_pauses_and_foreground_refreshes_immediately(self): self.run_fixture("foreground")
    def test_quick_reentry_is_not_missed(self): self.run_fixture("quick")
    def test_suppressed_list_rendering_expires_browse_lease(self): self.run_fixture("visibility")
    def test_retry_after_survives_page_reentry(self): self.run_fixture("throttle")
    def test_failures_back_off_with_bounded_jitter(self): self.run_fixture("failure")
    def test_response_from_previous_focus_session_is_discarded(self): self.run_fixture("stale")
    def test_public_host_renews_in_background_without_browsing(self): self.run_fixture("host_background")
    def test_registration_throttle_survives_host_toggle(self): self.run_fixture("host_throttle")
    def test_failed_renewal_retries_lease_then_resumes_normal_heartbeat(self): self.run_fixture("host_renew_failure")
    def test_page_exit_during_publication_does_not_send_queued_get(self): self.run_fixture("slow_publish")


if __name__ == "__main__":
    unittest.main()
