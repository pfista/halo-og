/* Diagnostic implementation included in player_control.c by halo_fidelity.py.
 * The fixture enters at the packed-action boundary, after controller processing.
 * It changes no weapon tags, aiming code, queue code, or simulation tick rate.
 * Records are buffered in memory and flushed after the experiment, not per frame.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "camera/observer.h"
#include "game/game_engine.h"
#include "interface/ui_widget.h"
#include "items/weapon_definitions.h"
#include "tag_files/tag_groups.h"
#include "tag_files/tag_files.h"
#include "../../port/linux/src/port_config.h"

enum { FIDELITY_CAPACITY = 65536 };
struct fidelity_record {
    long ms, tick, sample, player, flags, object, target;
    int kind;
    float x, y, z, i, j, k, trigger;
};
static struct fidelity_record fidelity_records[FIDELITY_CAPACITY];
static long fidelity_count, fidelity_overflow, fidelity_start, fidelity_sample;
static int fidelity_checked, fidelity_enabled, fidelity_finished, fidelity_shots = 48;
static float fidelity_rate = 100.f, fidelity_phase, fidelity_tap = 0.07f;
static int fidelity_previous_press = -1;
static int fidelity_idle;
static int fidelity_role;
static int fidelity_prepared;

/* Deterministic starting inventory on every simulation endpoint. Only the
 * diagnostic scenario changes; the loaded weapon tag and all firing code stay
 * intact. A slot number alone is not a reliable way to select a pistol. */
void fidelity_loadout(long player_index) {
    char const *setting = config_string("debug.test_input");
    struct player_datum *player;
    struct object_placement_data placement;
    real_point3d position;
    long definition, weapon;
    if (strncmp(setting, "fidelity", 8)) return;
    player = player_get(player_index);
    if (player->unit_index == NONE) return;
    definition = tag_loaded(WEAPON_DEFINITION_TAG, "weapons\\pistol\\pistol");
    if (definition == NONE) {
        fprintf(stderr, "FIDELITY_FIXTURE_ERROR stock pistol tag absent\n");
        return;
    }
    unit_delete_all_weapons(player->unit_index);
    object_placement_data_new(&placement, definition, NONE);
    weapon = object_new(&placement);
    if (weapon == NONE || !unit_add_weapon_to_inventory(player->unit_index, weapon, 2)) {
        fprintf(stderr, "FIDELITY_FIXTURE_ERROR could not equip pistol\n");
        return;
    }
    /* Fixed stock-map locations keep the idle peer beyond pistol autoaim
     * range and make spawn RNG differences irrelevant to the timing fixture. */
    if (DATUM_INDEX_TO_ABSOLUTE_INDEX(player_index) == 0) {
        position.x = 29.271f; position.y = -81.390f; position.z = 0.173f;
    } else {
        position.x = 85.242f; position.y = -157.766f; position.z = -0.020f;
    }
    object_set_position(player->unit_index, &position, NULL, NULL);
    fprintf(stderr, "FIDELITY_LOADOUT player=%ld tag=%s loaded=%d total=%d\n", player_index,
        tag_get_name(definition), (int)weapon_get(weapon)->weapon.magazines[0].rounds_loaded,
        (int)weapon_get(weapon)->weapon.magazines[0].rounds_total);
}

static void fidelity_prepare(void) {
    struct data_iterator iterator;
    struct player_datum *player;
    if (fidelity_prepared || (!fidelity_enabled && !fidelity_idle) ||
        !game_engine_running() || main_menu_is_active() || game_time_get() < 540) return;
    /* Reset the starting ammo on both simulations after the firing warmup.
     * This is fixture setup, completed two seconds before capture begins. */
    data_iterator_new(&iterator, player_data);
    while ((player = (struct player_datum *)data_iterator_next(&iterator)) != NULL) {
        struct unit_datum *unit = unit_try_and_get(player->unit_index);
        short slot;
        if (!unit) continue;
        for (slot = 0; slot < MAXIMUM_WEAPONS_PER_UNIT; slot++) {
            long index = unit->unit.weapon_object_indices[slot];
            struct weapon_datum *weapon = weapon_try_and_get(index);
            struct weapon_definition *definition;
            struct weapon_magazine_definition *magazine;
            if (!weapon || strcmp(tag_get_name(weapon->definition_index), "weapons\\pistol\\pistol")) continue;
            definition = weapon_definition_get(weapon->definition_index);
            magazine = TAG_BLOCK_GET_ELEMENT(&definition->weapon.magazines, 0, struct weapon_magazine_definition);
            weapon->weapon.magazines[0].rounds_loaded = MIN(magazine->rounds_total_initial, magazine->rounds_loaded_maximum);
            weapon->weapon.magazines[0].rounds_total = magazine->rounds_total_initial - weapon->weapon.magazines[0].rounds_loaded;
            fprintf(stderr, "FIDELITY_READY tick=%ld player=%ld loaded=%d total=%d\n", game_time_get(), iterator.datum_index,
                (int)weapon->weapon.magazines[0].rounds_loaded, (int)weapon->weapon.magazines[0].rounds_total);
        }
    }
    fidelity_prepared = 1;
}

static void fidelity_flush(void) {
    long n;
    if (!fidelity_enabled || fidelity_finished) return;
    fidelity_finished = 1;
    fprintf(stderr, "FTRACE {\"event\":\"meta\",\"schema\":1,\"scope\":\"packed_action_live_engine\","
        "\"role\":%d,\"legacy_lockstep\":%d,\"requested_shots\":%d,\"rate_dps\":%.9g,"
        "\"phase_ms\":%.9g,\"tap_ms\":%.9g,\"overflow\":%ld}\n",
        fidelity_role, FIDELITY_LEGACY, fidelity_shots, (double)fidelity_rate,
        (double)(fidelity_phase * 1000.f), (double)(fidelity_tap * 1000.f), fidelity_overflow);
    for (n = 0; n < fidelity_count; n++) {
        struct fidelity_record *r = &fidelity_records[n];
        fprintf(stderr, "FTRACE {\"event\":\"%c\",\"ms\":%ld,\"tick\":%ld,\"sample\":%ld,"
            "\"player\":%ld,\"flags\":%ld,\"object\":%ld,\"target\":%ld,"
            "\"x\":%.9g,\"y\":%.9g,\"z\":%.9g,\"i\":%.9g,\"j\":%.9g,\"k\":%.9g,\"trigger\":%.9g}\n",
            r->kind, r->ms, r->tick, r->sample, r->player, r->flags, r->object, r->target,
            (double)r->x, (double)r->y, (double)r->z, (double)r->i, (double)r->j, (double)r->k,
            (double)r->trigger);
    }
    fprintf(stderr, "FTRACE {\"event\":\"end\",\"records\":%ld}\n", fidelity_count);
    fflush(stderr);
}

static struct fidelity_record *fidelity_record(int kind) {
    struct fidelity_record *r;
    if (!fidelity_enabled || !fidelity_start || fidelity_finished) return NULL;
    if (fidelity_count >= FIDELITY_CAPACITY) { fidelity_overflow++; return NULL; }
    r = &fidelity_records[fidelity_count++];
    memset(r, 0, sizeof(*r));
    r->kind = kind;
    r->ms = system_milliseconds() - fidelity_start;
    r->tick = game_time_get();
    r->sample = fidelity_sample;
    r->object = r->target = NONE;
    return r;
}

static void fidelity_action(int kind, struct player_action const *a, long player) {
    struct fidelity_record *r = fidelity_record(kind);
    if (!r) return;
    r->player = player;
    r->flags = a->control_flags;
    r->x = a->desired_facing.yaw; r->y = a->desired_facing.pitch;
    r->i = a->throttle.i; r->j = a->throttle.j; r->trigger = a->primary_trigger;
    r->object = a->desired_weapon_index;
}

void fidelity_input(struct player_action *a, short seat) {
    double t, position, cycle;
    int magazine, round, press = -1;
    if (!fidelity_checked) {
        char const *setting = config_string("debug.test_input");
        fidelity_checked = 1;
        fidelity_idle = !strcmp(setting, "fidelity_idle");
        if (sscanf(setting, "fidelity:%d:%f:%f:%f", &fidelity_shots, &fidelity_rate,
                   &fidelity_phase, &fidelity_tap) == 4) {
            fidelity_phase /= 1000.f; fidelity_tap /= 1000.f;
            fidelity_enabled = 1;
            atexit(fidelity_flush);
        }
    }
    fidelity_prepare();
    if (fidelity_idle) {
        a->control_flags = 0; a->primary_trigger = 0.f;
        a->throttle.i = a->throttle.j = 0.f;
        a->desired_weapon_index = a->desired_grenade_index = a->desired_zoom_level = NONE;
        return;
    }
    if (!fidelity_enabled || seat != 0 ||
        !game_engine_running() || main_menu_is_active() || game_connection() == 0) return;
    if (game_time_get() < 600) {
        /* Exercise firing and impacts around a full turn before capture so
         * shader compilation cannot replay held fire during tick catch-up. */
        long tick = game_time_get();
        long warm = tick - 60;
        a->desired_facing.yaw = (float)fmod(tick * fidelity_rate / 30.0 * 0.017453292519943295, 6.283185307179586);
        if (a->desired_facing.yaw < 0.f) a->desired_facing.yaw += 6.283185307179586f;
        a->desired_facing.pitch = 0.f;
        a->throttle.i = a->throttle.j = 0.f;
        a->primary_trigger = warm >= 0 && warm < 360 && warm % 30 < 2 ? 1.f : 0.f;
        a->control_flags = a->primary_trigger ? FLAG(_unit_control_weapon_primary_trigger_bit) : 0;
        if (tick >= 450 && tick < 480) a->control_flags |= FLAG(_unit_control_weapon_reload_bit);
        a->desired_weapon_index = tick < 60 ? 0 : NONE;
        a->desired_grenade_index = a->desired_zoom_level = NONE;
        return;
    }
    if (!fidelity_start) {
        fidelity_start = system_milliseconds();
        fidelity_role = game_connection();
    }
    if (fidelity_finished) { a->control_flags = 0; a->primary_trigger = 0.f; return; }
    fidelity_sample++;
    t = (system_milliseconds() - fidelity_start) / 1000.0;
    position = t - 2.0 - fidelity_phase;
    magazine = position >= 0 ? (int)(position / 14.0) : -1;
    cycle = position >= 0 ? fmod(position, 14.0) : -1;
    round = cycle >= 0 ? (int)cycle : -1;
    if (magazine >= 0 && round < 12 && magazine * 12 + round < fidelity_shots &&
        cycle - round < fidelity_tap) press = magazine * 12 + round;
    a->desired_facing.yaw = (float)fmod(t * fidelity_rate * 0.017453292519943295, 6.283185307179586);
    if (a->desired_facing.yaw < 0.f) a->desired_facing.yaw += 6.283185307179586f;
    a->desired_facing.pitch = 0.f;
    a->throttle.i = a->throttle.j = 0.f;
    a->primary_trigger = press >= 0 ? 1.f : 0.f;
    a->control_flags = press >= 0 ? FLAG(_unit_control_weapon_primary_trigger_bit) : 0;
    if (cycle >= 12.2 && cycle < 12.35) a->control_flags |= FLAG(_unit_control_weapon_reload_bit);
    a->desired_weapon_index = t < 1.0 ? 0 : NONE;
    a->desired_grenade_index = a->desired_zoom_level = NONE;
    fidelity_action('a', a, seat);
    if (press >= 0 && press != fidelity_previous_press) {
        struct fidelity_record *r = fidelity_record('p');
        if (r) { r->object = press; r->x = a->desired_facing.yaw; }
    }
    fidelity_previous_press = press;
    if (position > ((fidelity_shots - 1) / 12) * 14 + (fidelity_shots - 1) % 12 + 3.0)
        fidelity_flush();
}

void fidelity_consumed(struct player_action const *a, long player) {
    fidelity_action('c', a, player);
}

void fidelity_ray(int stage, long weapon, long owner, long target,
    float x, float y, float z, float i, float j, float k) {
    struct unit_datum *unit = unit_try_and_get(owner);
    struct fidelity_record *r;
    if (!unit || unit->unit.player_index != local_player_get_player_index(0)) return;
    r = fidelity_record(stage);
    if (!r) return;
    r->object = weapon; r->player = owner; r->target = target;
    r->x = x; r->y = y; r->z = z; r->i = i; r->j = j; r->k = k;
    if (stage == 'b') fprintf(stderr, "FIDELITY_WEAPON %ld %s\n", weapon, tag_get_name(weapon));
}

void fidelity_camera(short seat, struct observer_result const *camera) {
    struct fidelity_record *r;
    if (!camera || seat != 0) return;
    r = fidelity_record('v');
    if (!r) return;
    r->player = seat;
    r->x = camera->position.x; r->y = camera->position.y; r->z = camera->position.z;
    r->i = camera->forward.i; r->j = camera->forward.j; r->k = camera->forward.k;
}
