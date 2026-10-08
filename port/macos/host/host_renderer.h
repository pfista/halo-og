#ifndef HALO_HOST_RENDERER_H
#define HALO_HOST_RENDERER_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif
enum host_renderer { HOST_RENDERER_ANGLE = 0, HOST_RENDERER_METAL = 1 };
/* Configure bundle paths before AppKit/SDL or any rebased guest is loaded. */
void host_renderer_set_paths(const char *executable, const char *resources);
int host_renderer_active(void);
int host_renderer_can_choose(void);
/* These read the current file, not a cached UI preference. Missing settings
 * default to Metal; an explicit ANGLE choice is retained. Invalid settings
 * fall back to ANGLE on launch; writes fail without replacing invalid files. */
int host_renderer_read(const char *support, char *error, size_t capacity);
int host_renderer_write(const char *support, int renderer, char *error, size_t capacity);
/* Success replaces this process. Failure explains why ANGLE should continue;
 * no config mutation, process monitor or crash retry is performed. */
void host_renderer_dispatch_native(int argc, char **argv, char *note, size_t capacity);
int host_renderer_default_guest(char *path, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
