/* EXPERIMENTAL_POWERUP_SYNC: a host-owned session policy, never saved in a
 * game variant or copied into a joining client's local preference. Plain int
 * declarations also allow the device settings UI to query it without cseries. */
#ifndef __NETWORK_POWERUP_SYNC_H
#define __NETWORK_POWERUP_SYNC_H

int network_powerup_sync_effective(void);
int network_powerup_sync_controlled_by_host(void);
int network_powerup_sync_pending(void);
int network_powerup_sync_host_enabled(void);
void network_powerup_sync_host_begin(void);
void network_powerup_sync_host_end(void);
void network_powerup_sync_client_begin(void);
void network_powerup_sync_client_end(void);
int network_powerup_sync_client_confirmed(void);
int network_powerup_sync_client_apply(int enabled);

#endif
