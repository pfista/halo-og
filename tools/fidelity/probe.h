/* Injected into isolated diagnostic source snapshots only. */
#ifndef HALO_FIDELITY_PROBE_H
#define HALO_FIDELITY_PROBE_H
struct player_action;
struct observer_result;
void fidelity_input(struct player_action *action, short seat);
void fidelity_loadout(long player_index);
void fidelity_consumed(struct player_action const *action, long player);
void fidelity_ray(int stage, long weapon, long owner, long target,
    float x, float y, float z, float i, float j, float k);
void fidelity_camera(short seat, struct observer_result const *camera);
#endif
