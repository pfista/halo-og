/* Low guest heap offsets deliberately have no native address bias. */
#include "../../linux/include/halo_custom_maps.h"
#include "../../linux/src/game_directory.h"
typedef unsigned int u32;
typedef struct SDL_Window SDL_Window;
unsigned long long SDL_GetWindowFlags(SDL_Window *window);
_Static_assert(sizeof(void *) == 4, "guest pointer layout");

u32 guest_test(u32 unused)
{
    char *directory = (char *)0x02000400;
    char *response = (char *)0x02000800;
    int *status = (int *)0x02000c00;
    int *retry_after_seconds = (int *)0x02000c04;
    if (halo_map_download_directory(directory, 1024) != 1 || directory[0] != '/') return 1;
    if (halo_map_download_directory(0, 0) != 0) return 2;
    if (halo_map_download_request((char *)0x02000200) != 2) return 3;
    if (halo_map_download_request(0) != 0) return 4;
    /* Every string argument, including an optional NULL expected digest,
       crosses the host import with the guest address bias applied once. */
    if (halo_arsenal_download_request((char *)0x02001000,
            (char *)0x02001100, (char *)0x02001200) != 2) return 10;
    if (halo_arsenal_download_request(0, 0, 0) != 0) return 11;
    if (halo_arsenal_download_request((char *)0x02001000,
            (char *)0x02001100, 0) != 2) return 12;
    if (halo_directory_http((char *)0x02000100, (char *)0x02000300,
            (char *)0x02000500, (char *)0x02000600, response, 1024, status, retry_after_seconds) != 3) return 5;
    if (*status != 201 || *retry_after_seconds != 30 || response[0] != 'o' || response[1] != 'k' || response[2]) return 6;
    if (halo_directory_http((char *)0x02000100, (char *)0x02000300,
            0, 0, response, 17, status, retry_after_seconds) != -7 || *status != 0 || *retry_after_seconds != 0) return 7;
    /* Window flags cross the ILP32 import ABI as a full unsigned 64-bit
       scalar, including bits above the guest's pointer width. */
    if (SDL_GetWindowFlags((SDL_Window *)0x12345678) != 0x8000000012345678ULL) return 8;
    if (SDL_GetWindowFlags(0) != 0) return 9;
    return 93;
}
