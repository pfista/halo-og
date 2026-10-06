/* Opened invites must remain within the chosen instance's save directory. */
#include "host.h"
#include "../../linux/src/p2p_invite.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(void) {
    char directory[] = "/tmp/halo-invite-test.XXXXXX";
    assert(mkdtemp(directory));
    assert(setenv("HALO_SAVE_ROOT", directory, 1) == 0);
    assert(host_is_discord_launch_url("discord-1556496882329460736://"));
    assert(host_is_discord_launch_url("discord-1556496882329460736://join"));
    assert(!host_is_discord_launch_url(NULL));
    assert(!host_is_discord_launch_url("discord-://"));
    assert(!host_is_discord_launch_url("discord-not-an-id://"));
    assert(!host_is_discord_launch_url("discord-1556496882329460736"));
    assert(!host_is_discord_launch_url("halo-og://join/short"));
    const char *invite = "halo-og://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";
    const char *legacy = "halo://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";
    assert(strlen(invite) + 1 <= P2P_LINK_SIZE);
    assert(p2p_invite_prefix_length("HALO-OG://JOIN/") == sizeof(P2P_LEGACY_INVITE_PREFIX) - 1);
    assert(p2p_invite_prefix_length("HALO://JOIN/") == sizeof(P2P_INVITE_PREFIX) - 1);
    assert(p2p_invite_prefix_length("HALO-OG-OPENCE://JOIN/") == sizeof(P2P_PRIVATE_INVITE_PREFIX) - 1);
    assert(!host_invite_received(NULL));
    assert(!host_invite_received("https://example.com/"));
    assert(!host_invite_received("discord-1556496882329460736://"));
    assert(!host_invite_received("halo://join/short"));
    assert(!host_invite_received("halo://join/0123456789ab0123456789abcdef0123456789abcdef"));
    assert(!host_invite_received("halo://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba987654321g"));
    assert(!host_invite_received("halo://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba98765432100"));
    assert(!host_invite_received("halo-og://join/short"));
    assert(!host_invite_received("halo-og://join/0123456789ab0123456789abcdef0123456789abcdef"));
    assert(!host_invite_received("halo-og://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba987654321g"));
    assert(!host_invite_received("halo-og://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba98765432100"));
    assert(host_invite_received(invite));
    char path[4096], text[P2P_LINK_SIZE];
    snprintf(path, sizeof(path), "%s/join_link.txt", directory);
    FILE *file = fopen(path, "r");
    assert(file && fgets(text, sizeof(text), file));
    fclose(file);
    assert(strcmp(text, invite) == 0);
    struct stat st;
    assert(stat(path, &st) == 0 && (st.st_mode & 0777) == 0600);
    assert(!host_invite_received("halo-og://join/short"));
    assert(stat(path, &st) == 0 && st.st_size == (off_t)strlen(invite));
    assert(host_invite_received(legacy));
    file = fopen(path, "r");
    assert(file && fgets(text, sizeof(text), file));
    fclose(file);
    assert(strcmp(text, legacy) == 0);
    assert(!host_invite_received("halo://join/short"));
    assert(stat(path, &st) == 0 && st.st_size == (off_t)strlen(legacy));
    const char *private_invite = "halo-og-opence://join/0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210";
    assert(strlen(private_invite) + 1 == P2P_LINK_SIZE);
    assert(host_invite_received(private_invite));
    file = fopen(path, "r");
    assert(file && fgets(text, sizeof(text), file));
    fclose(file);
    assert(strcmp(text, private_invite) == 0);
    assert(!host_invite_received("halo-og-opence://join/short"));
    assert(stat(path, &st) == 0 && st.st_size == (off_t)strlen(private_invite));
    assert(unlink(path) == 0 && rmdir(directory) == 0);
    puts("Mac invite validation, atomic delivery and private permissions passed");
    return 0;
}
