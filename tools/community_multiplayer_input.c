/* Community-map qualification input, loaded only in owned diagnostic peers.
 * This delivers ordinary native controls; it changes no Xbox gameplay rules.
 * Never loaded by a play launcher or packaged into a release.
 * No OS event posting, process memory access, or engine edits.
 * A controlled regular file contains sequence, type (key/mouse), code, hold_ms.
 */
#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned long seen;
static Uint64 release_at;
static int held_code, held_mouse;

static void make_event(SDL_Event *event, int code, int mouse, bool down)
{
    memset(event, 0, sizeof(*event));
    if (mouse) {
        event->type = down ? SDL_EVENT_MOUSE_BUTTON_DOWN : SDL_EVENT_MOUSE_BUTTON_UP;
        event->button.button = (Uint8)code;
        event->button.down = down;
    } else {
        event->type = down ? SDL_EVENT_KEY_DOWN : SDL_EVENT_KEY_UP;
        event->key.scancode = (SDL_Scancode)code;
        event->key.key = SDL_GetKeyFromScancode((SDL_Scancode)code, 0, false);
        event->key.down = down;
    }
    event->common.timestamp = SDL_GetTicksNS();
}

static bool diagnostic_poll_event(SDL_Event *event)
{
    const char *path = getenv("POC_DIAG_EVENT_FILE");
    if (event && path && *path) {
        Uint64 now = SDL_GetTicks();
        if (release_at && now >= release_at) {
            make_event(event, held_code, held_mouse, false);
            fprintf(stderr, "POC diagnostic SDL event: pid=%ld seq=%lu code=%d mouse=%d down=0\n", (long)getpid(), seen, held_code, held_mouse);
            release_at = 0;
            return true;
        }
        if (!release_at) {
            FILE *input = fopen(path, "r");
            if (input) {
                unsigned long seq;
                unsigned duration;
                int code;
                char type[16] = {0};
                int count = fscanf(input, "%lu %15s %d %u", &seq, type, &code, &duration);
                fclose(input);
                /* Private owned-process view motion; no OS cursor/event posting. */
                if (count == 4 && seq > seen && code >= -1000 && code <= 1000 &&
                    (!strcmp(type, "look_x") || !strcmp(type, "look_y"))) {
                    seen = seq;
                    memset(event, 0, sizeof(*event));
                    event->type = SDL_EVENT_MOUSE_MOTION;
                    event->motion.xrel = !strcmp(type, "look_x") ? (float)code : 0.0f;
                    event->motion.yrel = !strcmp(type, "look_y") ? (float)code : 0.0f;
                    event->common.timestamp = SDL_GetTicksNS();
                    fprintf(stderr, "POC diagnostic SDL event: pid=%ld seq=%lu code=%d mouse=0 down=0 type=%s\n", (long)getpid(), seen, code, type);
                    return true;
                }
                int mouse = strcmp(type, "mouse") == 0;
                if (count == 4 && seq > seen && duration >= 50 && duration <= 4000 &&
                    ((mouse && code >= 1 && code <= 5) ||
                     (!strcmp(type, "key") && code > 0 && code < SDL_SCANCODE_COUNT))) {
                    seen = seq;
                    held_code = code;
                    held_mouse = mouse;
                    release_at = now + duration;
                    make_event(event, code, mouse, true);
                    fprintf(stderr, "POC diagnostic SDL event: pid=%ld seq=%lu code=%d mouse=%d down=1 hold_ms=%u\n", (long)getpid(), seen, code, mouse, duration);
                    return true;
                }
            }
        }
    }
    return SDL_PollEvent(event);
}

__attribute__((used)) static struct {
    const void *replacement;
    const void *original;
} interpose_poll __attribute__((section("__DATA,__interpose"))) = {
    (const void *)diagnostic_poll_event,
    (const void *)SDL_PollEvent
};
