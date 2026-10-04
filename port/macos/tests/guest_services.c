/* Low guest heap offsets deliberately have no native address bias. */
#include "../../linux/include/halo_custom_maps.h"
#include "../../linux/src/game_directory.h"
typedef unsigned int u32;
_Static_assert(sizeof(void *) == 4, "guest pointer layout");

u32 guest_test(u32 unused)
{
    char *directory = (char *)0x02000400;
    char *response = (char *)0x02000800;
    int *status = (int *)0x02000c00;
    if (halo_map_download_directory(directory, 1024) != 1 || directory[0] != '/') return 1;
    if (halo_map_download_directory(0, 0) != 0) return 2;
    if (halo_map_download_request((char *)0x02000200) != 2) return 3;
    if (halo_map_download_request(0) != 0) return 4;
    if (halo_directory_http((char *)0x02000100, (char *)0x02000300,
            (char *)0x02000500, (char *)0x02000600, response, 1024, status) != 3) return 5;
    if (*status != 201 || response[0] != 'o' || response[1] != 'k' || response[2]) return 6;
    if (halo_directory_http((char *)0x02000100, (char *)0x02000300,
            0, 0, response, 17, status) != -7 || *status != 0) return 7;
    return 93;
}
