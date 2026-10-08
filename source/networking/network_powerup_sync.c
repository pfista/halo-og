/* EXPERIMENTAL_POWERUP_SYNC: latch the host's preference for the whole hosted
 * session. Rehosting applies a changed preference; loading another map does
 * not change it. A remote client defaults Off until reliable host settings
 * arrive, including when its own saved preference is On. */
#include "networking/network_powerup_sync.h"
#include "port_config.h"

static int powerup_sync_host_active;
static int powerup_sync_host_value;
static int powerup_sync_client_active;
static int powerup_sync_client_valid;
static int powerup_sync_client_value;

int network_powerup_sync_effective(void)
{
    if (powerup_sync_host_active) return powerup_sync_host_value;
    if (powerup_sync_client_active)
        return powerup_sync_client_valid && powerup_sync_client_value;
    return config_boolean("network.experimental_powerup_sync") != 0;
}

int network_powerup_sync_controlled_by_host(void)
{
    return powerup_sync_client_active && !powerup_sync_host_active;
}

int network_powerup_sync_pending(void)
{
    return powerup_sync_host_active &&
        ((config_boolean("network.experimental_powerup_sync") != 0) != powerup_sync_host_value);
}

int network_powerup_sync_host_enabled(void)
{
    return powerup_sync_host_active && powerup_sync_host_value;
}

void network_powerup_sync_host_begin(void)
{
    network_powerup_sync_client_end();
    powerup_sync_host_value = config_boolean("network.experimental_powerup_sync") != 0;
    powerup_sync_host_active = 1;
}

void network_powerup_sync_host_end(void)
{
    powerup_sync_host_active = 0;
    powerup_sync_host_value = 0;
}

void network_powerup_sync_client_begin(void)
{
    powerup_sync_client_active = 1;
    powerup_sync_client_valid = 0;
    powerup_sync_client_value = 0;
}

void network_powerup_sync_client_end(void)
{
    powerup_sync_client_active = 0;
    powerup_sync_client_valid = 0;
    powerup_sync_client_value = 0;
}

int network_powerup_sync_client_confirmed(void)
{
    return powerup_sync_client_active && powerup_sync_client_valid;
}

int network_powerup_sync_client_apply(int enabled)
{
    enabled = enabled != 0;
    if (!powerup_sync_client_active || powerup_sync_host_active ||
        (powerup_sync_client_valid && powerup_sync_client_value != enabled))
        return 0;
    powerup_sync_client_value = enabled;
    powerup_sync_client_valid = 1;
    return 1;
}
