/* Native macOS entry point. SDL video remains on the real main thread. */
#include "host.h"
#include "host_renderer.h"
#include "../../linux/src/p2p_invite.h"
#include "../native/host_menu.h"
#define SDL_MAIN_HANDLED
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <errno.h>
#include <mach-o/dyld.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
static char data_root[4096], save_root[4096];
static int create_directories(const char *path) {
    char buffer[4096];
    if (strlen(path) >= sizeof(buffer)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    strcpy(buffer, path);
    for (char *p = buffer + 1; *p; p++)
        if (*p == '/') {
            *p = 0;
            if (mkdir(buffer, 0755) && errno != EEXIST)
                return -1;
            *p = '/';
        }
    return mkdir(buffer, 0755) && errno != EEXIST ? -1 : 0;
}
void host_logf(int priority, const char *format, ...) {
    (void)priority;
    va_list a;
    va_start(a, format);
    vfprintf(stderr, format, a);
    fputc('\n', stderr);
    va_end(a);
}
void host_log(int priority, const char *text) { host_logf(priority, "%s", text); }
void host_fatal(const char *format, ...) {
    va_list a;
    va_start(a, format);
    vfprintf(stderr, format, a);
    fputc('\n', stderr);
    va_end(a);
    exit(1);
}
void host_abort(const char *reason) { host_fatal("guest abort: %s", reason); }
void host_exit(int code) {
    host_logf(HOST_LOG_INFO, "Game exited (%d)", code);
    host_menu_finish_game(code);
    exit(code);
}
int host_errno(void) { return host_linux_errno(errno); }
void host_android_path(int which, char *buffer, uint32_t size) {
    snprintf(buffer, size, "%s", which ? save_root : data_root);
}
extern char **environ;
static uint32_t make_boot(void) {
    size_t size = 0x20000;
    char *memory = host_low_map(size, PROT_READ | PROT_WRITE);
    if (!memory)
        host_fatal("No guest environment memory");
    struct halo_guest_boot *boot = (void *)memory;
    uint32_t *args = (void *)(memory + sizeof(*boot));
    uint32_t *env = args + 2;
    char *strings = (void *)(env + 256);
    unsigned count = 0;
    strcpy(strings, "halo");
    args[0] = (uint32_t)(uintptr_t)strings;
    args[1] = 0;
    strings += 5;
    for (char **p = environ; *p && count < 255; p++) {
        size_t n = strlen(*p) + 1;
        if (strings + n > memory + size)
            break;
        memcpy(strings, *p, n);
        env[count++] = (uint32_t)(uintptr_t)strings;
        strings += n;
    }
    env[count] = 0;
    *boot = (struct halo_guest_boot){1, (uint32_t)(uintptr_t)args, (uint32_t)(uintptr_t)env,
                                     HALO_MACOS_PAGE};
    return (uint32_t)(uintptr_t)boot;
}
extern void macos_enter_guest_stack(void *top, uint32_t boot) __attribute__((noreturn));
int main(int argc, char **argv) {
    const char *image_argument = NULL;
    int force_angle = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--renderer-angle")) {
            force_angle = 1;
            continue;
        }
        if (p2p_invite_prefix_length(argv[i]) || host_is_discord_launch_url(argv[i]))
            continue;
        if (image_argument) {
            fprintf(stderr, "Usage: %s [--renderer-angle] [halo_guest.elf] [" P2P_INVITE_PREFIX "invite]\n", argv[0]);
            return 2;
        }
        image_argument = argv[i];
    }
    setbuf(stderr, NULL);
    host_install_signal_handlers();
    char executable[4096], full_executable[4096], resources[4096], default_image[4096], default_data[4096],
        default_saves[4096];
    uint32_t executable_size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &executable_size))
        host_fatal("Executable path is too long");
    snprintf(full_executable, sizeof(full_executable), "%s", executable);
    char *slash = strrchr(executable, '/');
    if (!slash)
        host_fatal("Cannot locate application resources");
    *slash = 0;
    snprintf(resources, sizeof(resources), "%s/../Resources", executable);
    host_renderer_set_paths(full_executable, resources);
    if (!host_renderer_default_guest(default_image, sizeof(default_image)))
        host_fatal("Guest image path is too long");
    snprintf(default_data, sizeof(default_data), "%s/GameData", resources);
    if (!image_argument && access(default_data, F_OK)) {
        char config[4096];
        snprintf(config, sizeof(config), "%s/GameDataPath.txt", resources);
        FILE *setting = fopen(config, "r");
        if (setting) {
            if (fgets(default_data, sizeof(default_data), setting))
                default_data[strcspn(default_data, "\r\n")] = 0;
            fclose(setting);
        }
    }
    const char *home = getenv("HOME");
    if (!home)
        host_fatal("HOME is not set");
    snprintf(default_saves, sizeof(default_saves),
             "%s/Library/Application Support/Halo OG", home);
    const char *saves = getenv("HALO_SAVE_ROOT");
    if (!saves)
        saves = !image_argument ? default_saves : "build/macos/saves";
    if (create_directories(saves) || !realpath(saves, save_root))
        host_fatal("Cannot open saves folder: %s", saves);
    char renderer_note[256] = "";
#if !defined(HALO_MACOS_NATIVE_METAL)
    if (!image_argument) {
        int saved_renderer = host_renderer_read(save_root, renderer_note, sizeof(renderer_note));
        if (force_angle)
            snprintf(renderer_note, sizeof(renderer_note), "One-launch ANGLE recovery override; the saved renderer was not changed.");
        else if (saved_renderer == HOST_RENDERER_METAL)
            host_renderer_dispatch_native(argc, argv, renderer_note, sizeof(renderer_note));
    }
#else
    if (force_angle) {
        fprintf(stderr, "Use the normal app executable (Contents/MacOS/halo) with --renderer-angle for recovery.\n");
        return 2;
    }
#endif
    if (!image_argument) host_menu_initialize_application();
    SDL_SetMainReady();
    SDL_SetHint(SDL_HINT_VIDEO_MAC_FULLSCREEN_SPACES, "0");
    SDL_SetHint(SDL_HINT_VIDEO_MAC_FULLSCREEN_MENU_VISIBILITY, "1");
    /* Keep native settings/file panels and the menu bar above borderless video. */
    SDL_SetHint(SDL_HINT_WINDOW_ALLOW_TOPMOST, "0");
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO))
        host_fatal("Cannot initialize display: %s", SDL_GetError());
    const char *root = getenv("HALO_DATA_ROOT");
    if (!root) root = !image_argument ? default_data : "assets";
    char selected_data[4096];
    if (!image_argument) {
        if (!host_menu_prepare(save_root, root, selected_data, sizeof(selected_data))) return 0;
        root = selected_data;
    }
    if (!realpath(root, data_root))
        host_fatal("Game data folder is missing: %s", root);
    if (!image_argument) {
        char log_path[4096];
        snprintf(log_path, sizeof(log_path), "%s/halo.log", save_root);
        freopen(log_path, "w", stderr);
        setbuf(stderr, NULL);
    }
    host_logf(HOST_LOG_INFO, "App executable: %s", full_executable);
    host_logf(HOST_LOG_INFO, "Renderer active: %s; changes apply on next launch",
        host_renderer_active() == HOST_RENDERER_METAL ? "Native Metal" : "ANGLE");
    if (*renderer_note) host_logf(HOST_LOG_WARN, "%s", renderer_note);
    char build_info_path[4096], build_info_line[256];
    snprintf(build_info_path, sizeof(build_info_path), "%s/BuildInfo.txt", resources);
    FILE *build_info = fopen(build_info_path, "r");
    if (build_info) {
        while (fgets(build_info_line, sizeof(build_info_line), build_info)) {
            build_info_line[strcspn(build_info_line, "\r\n")] = 0;
            host_logf(HOST_LOG_INFO, "%s", build_info_line);
        }
        fclose(build_info);
    }
    setenv("HALO_DATA_ROOT", data_root, 1);
    setenv("HALO_SAVE_ROOT", save_root, 1);
    const SDL_DisplayMode *display = SDL_GetDesktopDisplayMode(SDL_GetPrimaryDisplay());
    if (display && display->h > 0) {
        char width[32];
        snprintf(width, sizeof(width), "%d", (480 * display->w / display->h) & ~1);
        setenv("HALO_DISPLAY_WIDTH", width, 0);
        host_logf(HOST_LOG_INFO, "Display %dx%d; game aspect %sx480", display->w,
                  display->h, getenv("HALO_DISPLAY_WIDTH"));
    }
    const char *image_path = image_argument ? image_argument : default_image;
    FILE *file = fopen(image_path, "rb");
    if (!file)
        host_fatal("Cannot open guest image: %s", image_path);
    fseek(file, 0, SEEK_END);
    long size = ftell(file);
    rewind(file);
    if (size <= 0 || size > 256 * 1024 * 1024)
        host_fatal("Invalid guest image size");
    void *image = malloc((size_t)size);
    if (!image || fread(image, 1, (size_t)size, file) != (size_t)size)
        host_fatal("Cannot read guest image");
    fclose(file);
    if (host_load_image(image, (size_t)size))
        host_fatal("Cannot load rebased game image");
    free(image);
    uint32_t boot = make_boot();
    size_t stack_size = 16 * 1024 * 1024;
    char *stack = host_low_map(stack_size + HALO_MACOS_PAGE, PROT_READ | PROT_WRITE);
    if (!stack)
        host_fatal("Cannot allocate main stack");
    mprotect(stack, HALO_MACOS_PAGE, PROT_NONE);
    host_logf(HOST_LOG_INFO, "Halo ARM64 starting: data %s; saves %s", data_root, save_root);
    if (!image_argument) host_menu_begin_game();
    macos_enter_guest_stack(stack + stack_size + HALO_MACOS_PAGE, boot);
}
