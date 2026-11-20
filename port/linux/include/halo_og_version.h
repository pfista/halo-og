#ifndef HALO_OG_VERSION_H
#define HALO_OG_VERSION_H

/* Shared product version for the game menu and platform packages.
 * Installer build numbers remain separate.
 *
 * The version states which builds play together. While the major version is 0,
 * builds with the same minor version do (every 0.6.x); from 1.0, builds with
 * the same major version do. So a change that machines must agree on, to what
 * they send each other or to the simulation, needs a new minor version before
 * 1.0 and a new major version after it. HALO_PORT_NETWORK_VERSION
 * (halo_port_limits.h) follows this version and enforces the rule in the game. */
#define HALO_OG_VERSION "0.6.0"

/* Historical reconstruction target, independent of the selected game data. */
#define HALO_OG_ENGINE_BUILD_NUMBER "01.01.14.2342"

#endif
