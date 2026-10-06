"""Exercise production Overshield decay, network vitality and HUD warning flags.

The damage/HUD functions, enums, HUD state layout and vitality codec are extracted
from production C. A deterministic fixture supplies player/object lookup and
captures HUD sound flags. This checks feedback decisions, not audible playback,
socket transport, rendering, or original Xbox parity. C long is mapped to
int32_t to preserve the game's ILP32 types on native LP64 test hosts.
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools.test_network_pings import block

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    """Find a definition, skipping its earlier forward declaration."""
    match = re.search(
        rf"^(?:static\s+)?(?:struct\s+\w+\s*\*|\w+\s+)"
        rf"{re.escape(name)}\s*\([^;{{}}]*\)\s*\{{", source, re.M)
    if not match:
        raise ValueError(f"Missing production function: {name}")
    return block(source[match.start():], match[0])


def enum_containing(source, name):
    start = source.rindex("enum", 0, source.index(name))
    return block(source[start:], "enum") + ";"


PREFIX = r'''
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
/* PRODUCTION TYPES AND CONSTANTS */
typedef word message_header;
typedef struct { real x, y, z; } real_point3d;
#define NONE (-1)
#define TRUE 1
#define FALSE 0
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#define STACK_BUFFER_LENGTH 2
#define csmemset memset
#define match_assert(path,line,condition) assert(condition)
#define TAG_BLOCK_GET_ELEMENT(block,index,type) (&mocked_falling_damage)
#define object_datum unit_datum

struct player_datum;
/* PRODUCTION DECLARATIONS */
/* Only fields used by the extracted functions are supplied for game objects. */
struct unit_datum {
    int32_t definition_index;
    struct {
        uint32_t flags;
        word damage_flags;
        real body_vitality, shield_vitality;
        real current_body_damage, recent_body_damage;
        real current_shield_damage, recent_shield_damage;
        real maximum_shield_vitality;
        int32_t body_damage_decay_timer, shield_damage_decay_timer;
        short shield_stun_ticks, owner_team_index;
    } object;
};
struct player_datum { short local_player_index; int32_t unit_index; };
struct unit_definition { int unused; };
struct unit_hud_interface_definition { int warning_sounds; };
struct object_definition { struct { struct { int32_t index; } collision_model; } object; };
struct collision_model {
    struct {
        struct { int32_t index; } shield_recharging_effect;
        real runtime_shield_recharge_velocity;
    } resistance;
};
struct damage_data { real scale; uint32_t flags; };
struct game_globals_falling_damage { struct { int32_t index; } falling_damage; };
enum { _game_difficulty_value_enemy_recharge };

/* Local players, one remote player and one object with no player. */
enum { REMOTE_PLAYER = MAXIMUM_NUMBER_OF_LOCAL_PLAYERS,
    NON_PLAYER_UNIT = MAXIMUM_NUMBER_OF_LOCAL_PLAYERS + 1,
    FIXTURE_UNITS = MAXIMUM_NUMBER_OF_LOCAL_PLAYERS + 2 };
static struct unit_datum units[FIXTURE_UNITS];
static struct player_datum players[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS + 1];
static struct unit_hud_globals globals, *unit_hud_globals = &globals;
static struct { boolean show_hud; } scripted = { TRUE }, *hud_scripted_globals = &scripted;
static struct unit_definition unit_definition;
static struct unit_hud_interface_definition hud_definition;
static struct object_definition object_definition = {{{0}}};
static struct collision_model collision_model;
static struct game_globals_falling_damage mocked_falling_damage;
static uint32_t captured_sound_flags[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static boolean distributed_client, distributed_damage_authorized;
static int32_t now;
/* PRODUCTION HISTORY GLOBAL */
static struct unit_datum *unit_try_and_get(int32_t index);
/* Non-aftermath event cases are omitted; only their shared validation is mocked. */
struct distributed_damage_event {
    int damage;
    byte kind;
    int32_t object_index;
    uint32_t being_damaged_flags;
    real shield_damage, body_damage, body_damage_multiplier, total_damage;
    short body_part;
};
static unsigned damage_replayed_events, aftermath_calls;
static boolean network_objects_client_has(int32_t index) { return unit_try_and_get(index) != NULL; }
static void *object_try_and_get_and_verify_type(int32_t index, int mask) {
    (void)mask; return unit_try_and_get(index);
}
static boolean distributed_damage_numbers_valid(void const *damage) { (void)damage; return TRUE; }
static boolean distributed_damage_to_data(void const *source, struct damage_data *damage) {
    (void)source; memset(damage, 0, sizeof(*damage)); return TRUE;
}
static boolean distributed_real_valid(real value) { return isfinite(value); }
static void damage_replay_aftermath(int32_t index, struct damage_data *damage,
    uint32_t flags, real shield, real body, real multiplier, short part) {
    (void)index; (void)damage; (void)flags; (void)shield; (void)body; (void)multiplier; (void)part;
    aftermath_calls++;
}
/* State decoding is inert here: timestamp forwarding is exercised with complete
 * state structs, while the actual vitality pack/unpack functions remain in use. */
static word distributed_unit_state_read(byte const *data, byte const *end,
    struct distributed_unit_state *state) {
    if ((size_t)(end - data) < sizeof(*state)) return 0;
    memcpy(state, data, sizeof(*state)); return sizeof(*state);
}

static struct player_datum *player_get(int32_t index) {
    assert(index >= 0 && index <= REMOTE_PLAYER); return &players[index];
}
static int32_t player_index_from_unit_index(int32_t index) {
    for (int32_t i = 0; i <= REMOTE_PLAYER; i++)
        if (players[i].unit_index == index) return i;
    return NONE;
}
static int32_t local_player_get_player_index(short index) {
    assert(index >= 0 && index < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS);
    for (int32_t i = 0; i <= REMOTE_PLAYER; i++)
        if (players[i].local_player_index == index) return i;
    return NONE;
}
static struct unit_datum *unit_try_and_get(int32_t index) {
    return index >= 0 && index < FIXTURE_UNITS ? &units[index] : NULL;
}
static struct unit_datum *unit_get(int32_t index) {
    struct unit_datum *unit = unit_try_and_get(index); assert(unit); return unit;
}
static struct unit_datum *object_get(int32_t index) { return unit_get(index); }
static struct unit_definition const *unit_definition_get(int32_t index) {
    (void)index; return &unit_definition;
}
static int32_t unit_definition_get_active_hud_index(struct unit_definition const *definition,
    boolean split_screen) { (void)definition; (void)split_screen; return 0; }
static int local_player_count(void) { return MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; }
static struct unit_hud_interface_definition const *unit_hud_interface_definition_get(int32_t index) {
    (void)index; return &hud_definition;
}
static boolean cinematic_in_progress(void) { return FALSE; }
static boolean game_engine_has_shield(int32_t player_index) { (void)player_index; return TRUE; }
static boolean game_engine_running(void) { return TRUE; }
static boolean network_game_distributed_client(void) { return distributed_client; }
static real game_difficulty_get_team_value(int value, short team) { (void)value; (void)team; return 1.0f; }
static void hud_play_sound(short local_index, uint32_t flags, int const *warnings,
    int32_t *handles, word *previous_flags) {
    (void)warnings; (void)handles; (void)previous_flags;
    assert(local_index >= 0 && local_index < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS);
    captured_sound_flags[local_index] = flags;
}
static struct object_definition *object_definition_get(int32_t index) {
    (void)index; return &object_definition;
}
static struct collision_model *collision_model_definition_get(int32_t index) {
    (void)index; return &collision_model;
}
static void object_deplete_shield(int32_t index) {
    SET_FLAG(units[index].object.damage_flags, _object_shield_depleted_bit, TRUE);
}
static void damage_effect_new_on_object(int32_t effect, int32_t index) { (void)effect; (void)index; }
static void object_permutation_shield_regions(int32_t index, boolean active) { (void)index; (void)active; }
static void damage_data_new(struct damage_data *damage, int32_t index) {
    (void)index; memset(damage, 0, sizeof(*damage));
}
static void object_cause_damage(struct damage_data *damage, int32_t object_index,
    int32_t node, int32_t region, int32_t material, void *normal) {
    (void)damage; (void)object_index; (void)node; (void)region; (void)material; (void)normal;
    assert(0); /* The fixture does not set any act-of-god damage flags. */
}
static int32_t get_return_eip(void) { return 0; }
static int32_t game_time_get(void) { return now; }
static void match_assert_stack_frame(char const *path, int line) { (void)path; (void)line; }

/* PRODUCTION FUNCTIONS */
'''

HARNESS = r'''
static void reset(void) {
    memset(units, 0, sizeof(units)); memset(&globals, 0, sizeof(globals));
    memset(captured_sound_flags, 0, sizeof(captured_sound_flags));
    /* RESET HISTORY */
    for (int i = 0; i < FIXTURE_UNITS; i++) {
        units[i].object.body_vitality = 1.0f;
        units[i].object.shield_vitality = 3.0f;
        units[i].object.maximum_shield_vitality = 1.0f;
        units[i].object.body_damage_decay_timer = NONE;
        units[i].object.shield_damage_decay_timer = NONE;
    }
    for (int i = 0; i <= REMOTE_PLAYER; i++) {
        players[i].unit_index = i;
        players[i].local_player_index = i == REMOTE_PLAYER ? NONE : i;
    }
    for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) {
        initialize_hud_state(get_hud_state(i));
        hud_update_unit_local_player(i);
    }
    collision_model.resistance.runtime_shield_recharge_velocity = 0.033333335f;
    aftermath_calls = damage_replayed_events = 0;
    now = 100; distributed_client = FALSE;
}
static boolean sound(short local_index, int flag) {
    return TEST_FLAG(captured_sound_flags[local_index], flag);
}
static void update_hud(short local_index) {
    hud_update_unit_local_player(local_index);
    hud_play_unit_sounds(player_get(local_player_get_player_index(local_index)), TRUE);
}
static void local_tick(int32_t unit_index) {
    object_damage_update(unit_index); now++;
    short local_index = player_get(player_index_from_unit_index(unit_index))->local_player_index;
    if (local_index != NONE) update_hud(local_index);
}
static struct distributed_unit_state packet(short player_index, real shield, real current, real recent) {
    struct distributed_unit_state state = {0};
    state.player_index = player_index;
    state.unit_index = players[player_index].unit_index;
    SET_FLAG(state.flags, _distributed_unit_alive_bit, TRUE);
    state.body_vitality = distributed_vitality_pack(1.0f);
    state.shield_vitality = distributed_vitality_pack(shield);
    state.current_shield_damage = distributed_vitality_pack(current);
    state.recent_shield_damage = distributed_vitality_pack(recent);
    return state;
}
static real apply_packet(short player_index, int32_t host_time, struct distributed_unit_state const *state) {
    real passive_loss = distributed_passive_shield_loss(player_index, host_time, state);
    struct damage_network_state damage = {0};
    damage.body_vitality = distributed_vitality_unpack(state->body_vitality);
    damage.shield_vitality = distributed_vitality_unpack(state->shield_vitality);
    damage.current_shield_damage = distributed_vitality_unpack(state->current_shield_damage);
    damage.recent_shield_damage = distributed_vitality_unpack(state->recent_shield_damage);
    damage.shield_over_charging = TEST_FLAG(state->flags, _distributed_unit_shield_over_charging_bit);
    damage_set_network_state(state->unit_index, &damage, passive_loss);
    return passive_loss;
}
static real decay(real shield, int ticks) {
    for (int tick = 0; tick < ticks && shield > 1.0f; tick++) {
        real overcharge = shield - 1.0f;
        shield = overcharge < 0.00074074074f ? 1.0f : shield - 0.00074074074f;
    }
    return shield;
}
static void local_lifecycle(void) {
    reset();
    units[0].object.shield_vitality = get_hud_state(0)->last_shield_vitality = 1.0f;
    SET_FLAG(units[0].object.damage_flags, _object_shield_over_charging_bit, TRUE);
    int charge_ticks = 0;
    while (TEST_FLAG(units[0].object.damage_flags, _object_shield_over_charging_bit)) {
        assert(++charge_ticks < 100); local_tick(0);
        assert(!sound(0, _unit_hud_shield_damage));
    }
    assert(units[0].object.shield_vitality == 3.0f);
    int drain_ticks = 0;
    while (units[0].object.shield_vitality > 1.0f) {
        assert(++drain_ticks <= TICKS_PER_SECOND * 90); local_tick(0);
        assert(!sound(0, _unit_hud_shield_damage));
        assert(get_hud_state(0)->last_shield_vitality == units[0].object.shield_vitality);
    }
    assert(drain_ticks == TICKS_PER_SECOND * 90);
    assert(units[0].object.shield_vitality == 1.0f);
}
static void local_damage(void) {
    reset(); units[0].object.shield_vitality -= 0.25f;
    int damage_sound_ticks = 0;
    for (int tick = 0; tick < 60; tick++) {
        local_tick(0);
        if (sound(0, _unit_hud_shield_damage)) damage_sound_ticks++;
        if (tick >= 15) assert(!sound(0, _unit_hud_shield_damage));
    }
    assert(damage_sound_ticks > 0);
    reset();
    units[0].object.shield_vitality = get_hud_state(0)->last_shield_vitality = 1.0f;
    units[0].object.shield_vitality -= 0.25f;
    units[0].object.shield_stun_ticks = 30;
    update_hud(0); assert(sound(0, _unit_hud_shield_damage));
    reset(); units[0].object.body_vitality -= 0.125f;
    update_hud(0); assert(sound(0, _unit_hud_minor_damage));
}
static void multiple_players(void) {
    reset();
    for (int tick = 0; tick < 30; tick++) {
        for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) object_damage_update(i);
        object_damage_update(REMOTE_PLAYER); now++;
        for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) {
            update_hud(i); assert(!sound(i, _unit_hud_shield_damage));
            assert(get_hud_state(i)->last_shield_vitality == units[i].object.shield_vitality);
        }
    }
    units[2].object.shield_vitality -= 0.25f;
    for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) update_hud(i);
    for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++)
        assert(sound(i, _unit_hud_shield_damage) == (i == 2));
}
static void network_passive_decay(void) {
    const int intervals[] = {1, GAME_STATE_INTERVAL_TICKS, 18, TICKS_PER_SECOND};
    for (unsigned schedule = 0; schedule < sizeof(intervals)/sizeof(intervals[0]); schedule++) {
        reset(); distributed_client = TRUE;
        real host_shield = 3.0f;
        struct distributed_unit_state state = packet(0, host_shield, 0, 0);
        assert(apply_packet(0, now, &state) == 0.0f);
        while (host_shield > 1.0f) {
            host_shield = decay(host_shield, intervals[schedule]);
            now += intervals[schedule];
            state = packet(0, host_shield, 0, 0);
            assert(apply_packet(0, now, &state) > 0.0f); update_hud(0);
            assert(!sound(0, _unit_hud_shield_damage));
        }
        assert(units[0].object.shield_vitality == 1.0f);
    }
}
static void network_real_damage(void) {
    reset(); distributed_client = TRUE;
    struct distributed_unit_state state = packet(0, 3.0f, 0, 0);
    assert(apply_packet(0, now, &state) == 0.0f);
    now += GAME_STATE_INTERVAL_TICKS;
    state = packet(0, decay(3.0f, GAME_STATE_INTERVAL_TICKS) - 0.25f, 0.25f, 0.25f);
    assert(apply_packet(0, now, &state) == 0.0f);
    update_hud(0); assert(sound(0, _unit_hud_shield_damage));

    /* A hit marker must win even if its vitality reduction is indistinguishable
     * from a passive decay update after rounding. */
    reset(); distributed_client = TRUE;
    state = packet(0, 3.0f, 0, 0); apply_packet(0, now, &state);
    now++; state = packet(0, decay(3.0f, 1), 0.0625f, 0.0625f);
    assert(apply_packet(0, now, &state) == 0.0f);
    update_hud(0); assert(sound(0, _unit_hud_shield_damage));

    /* An explicit aftermath notice must also prevent passive classification. */
    reset(); distributed_client = TRUE;
    state = packet(0, 3.0f, 0, 0); apply_packet(0, now, &state);
    network_distributed_note_shield_damage(0, now + 1);
    now++; state = packet(0, decay(3.0f, 1), 0, 0);
    assert(apply_packet(0, now, &state) == 0.0f);
    update_hud(0); assert(sound(0, _unit_hud_shield_damage));
    now++; state = packet(0, decay(3.0f, 2), 0, 0);
    assert(apply_packet(0, now, &state) > 0.0f);
    update_hud(0); assert(sound(0, _unit_hud_shield_damage)); /* Prior hit hold survives. */

    /* Old damage markers may legitimately decay while Overshield drains. */
    reset(); distributed_client = TRUE;
    state = packet(0, 3.0f, 0.5f, 0.5f); apply_packet(0, now, &state);
    now += GAME_STATE_INTERVAL_TICKS;
    state = packet(0, decay(3.0f, GAME_STATE_INTERVAL_TICKS),
                   0.5f - GAME_STATE_INTERVAL_TICKS * 0.016666668f, 0.5f);
    assert(apply_packet(0, now, &state) > 0.0f);
    update_hud(0); assert(!sound(0, _unit_hud_shield_damage));
}
static void uncertain_network_transitions(void) {
    const int intervals[] = {0, -1, TICKS_PER_SECOND + 1};
    for (unsigned i = 0; i < sizeof(intervals)/sizeof(intervals[0]); i++) {
        reset(); distributed_client = TRUE;
        struct distributed_unit_state state = packet(0, 3.0f, 0, 0);
        apply_packet(0, now, &state);
        state = packet(0, decay(3.0f, intervals[i] > 0 ? intervals[i] : 1), 0, 0);
        assert(distributed_passive_shield_loss(0, now + intervals[i], &state) == 0.0f);
    }
    reset(); distributed_client = TRUE;
    struct distributed_unit_state state = packet(0, 3.0f, 0, 0);
    apply_packet(0, now, &state);
    state = packet(0, decay(3.0f, 1), 0, 0);
    SET_FLAG(state.flags, _distributed_unit_shield_over_charging_bit, TRUE);
    assert(distributed_passive_shield_loss(0, now + 1, &state) == 0.0f);

    reset(); distributed_client = TRUE;
    state = packet(0, 3.0f, 0, 0); apply_packet(0, now, &state);
    state = packet(0, 0.99f, 0, 0);
    assert(distributed_passive_shield_loss(0, now + 1, &state) == 0.0f);

    reset(); distributed_client = TRUE;
    state = packet(0, 3.0f, 0, 0); apply_packet(0, now, &state);
    state = packet(0, decay(3.0f, 1), 0, 0);
    state.unit_index = NON_PLAYER_UNIT;
    assert(distributed_passive_shield_loss(0, now + 1, &state) == 0.0f);
}
static void sentinel_lifecycle(void) {
    reset(); initialize_hud_state(get_hud_state(0));
    assert(get_hud_state(0)->last_shield_vitality == -1.0f);
    hud_tick_shield(0, 0.00074074074f);
    assert(get_hud_state(0)->last_shield_vitality == -1.0f);
    object_damage_update(0); now++; update_hud(0);
    assert(get_hud_state(0)->last_shield_vitality == units[0].object.shield_vitality);
    assert(!sound(0, _unit_hud_shield_damage));
    struct unit_hud_globals before = globals;
    hud_tick_shield(NONE, 0.00074074074f);
    hud_tick_shield(REMOTE_PLAYER, 0.00074074074f);
    object_damage_update(NON_PLAYER_UNIT);
    assert(!memcmp(&globals, &before, sizeof(globals)));
}
static void network_multiple_players(void) {
    reset(); distributed_client = TRUE;
    for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) {
        struct distributed_unit_state state = packet(i, 3.0f, 0, 0);
        assert(apply_packet(i, now, &state) == 0.0f);
    }
    now += GAME_STATE_INTERVAL_TICKS;
    for (int i = 0; i < MAXIMUM_NUMBER_OF_LOCAL_PLAYERS; i++) {
        real loss = i == 2 ? 0.25f : 0.0f;
        struct distributed_unit_state state = packet(i, decay(3.0f, GAME_STATE_INTERVAL_TICKS) - loss,
                                                      loss, loss);
        assert((apply_packet(i, now, &state) > 0.0f) == (i != 2));
        update_hud(i); assert(sound(i, _unit_hud_shield_damage) == (i == 2));
    }
    struct distributed_unit_state remote = packet(REMOTE_PLAYER, 3.0f, 0, 0);
    assert(distributed_passive_shield_loss(REMOTE_PLAYER, now, &remote) == 0.0f);
    remote = packet(REMOTE_PLAYER, decay(3.0f, 1), 0, 0);
    assert(distributed_passive_shield_loss(REMOTE_PLAYER, now + 1, &remote) == 0.0f);
}
static void receive_state(int32_t host_time, struct distributed_unit_state state) {
    struct { struct distributed_message_header header; struct distributed_unit_state state; } message = {
        {.type = _distributed_message_unit_states, .count = 1, .game_time = host_time}, state
    };
    fixture_dispatch(message.header, &message, sizeof(message));
}
static void receive_event(int32_t host_time, real shield_damage) {
    struct {
        struct distributed_message_header header;
        struct distributed_damage_event event;
    } message = {
        {.type = _distributed_message_damage_events, .count = 1, .game_time = host_time},
        {.kind = _damage_event_aftermath, .object_index = 0, .shield_damage = shield_damage}
    };
    fixture_dispatch(message.header, &message, sizeof(message));
}
static void host_timestamps_and_events(void) {
    reset(); distributed_client = TRUE; now = 1000;
    receive_state(50, packet(0, 3.0f, 0, 0));
    receive_state(56, packet(0, decay(3.0f, 6), 0, 0)); update_hud(0);
    assert(!sound(0, _unit_hud_shield_damage));
    assert(distributed_shield_histories[0].host_time == 56);
    assert(now == 1000); /* Classification uses the message time, not local time. */

    reset(); distributed_client = TRUE;
    receive_state(50, packet(0, 3.0f, 0, 0));
    receive_event(52, 0.00001f);
    assert(aftermath_calls == 1 && distributed_shield_histories[0].hit_pending);
    receive_state(51, packet(0, decay(3.0f, 1), 0, 0));
    assert(distributed_shield_histories[0].hit_pending);
    receive_state(52, packet(0, decay(3.0f, 2), 0, 0)); update_hud(0);
    assert(!distributed_shield_histories[0].hit_pending);
    assert(sound(0, _unit_hud_shield_damage));
    receive_state(53, packet(0, decay(3.0f, 3), 0, 0));
    assert(distributed_shield_histories[0].host_time == 53);

    reset(); distributed_client = TRUE;
    receive_state(50, packet(0, 3.0f, 0, 0));
    receive_event(51, 0.0f); /* Body-only aftermath cannot poison shield decay. */
    assert(aftermath_calls == 1 && !distributed_shield_histories[0].hit_pending);
    receive_state(51, packet(0, decay(3.0f, 1), 0, 0)); update_hud(0);
    assert(!sound(0, _unit_hud_shield_damage));
    receive_event(51, 0.00001f); /* A late event for a state already applied. */
    assert(!distributed_shield_histories[0].hit_pending);
    update_hud(0); assert(sound(0, _unit_hud_shield_damage));
    real restored_baseline = get_hud_state(0)->last_shield_vitality;
    assert(restored_baseline == 3.0f);
    receive_event(51, 0.00001f); /* Duplicate aftermath cannot restore twice. */
    assert(get_hud_state(0)->last_shield_vitality == restored_baseline);
    receive_state(52, packet(0, decay(3.0f, 2), 0, 0)); update_hud(0);
    assert(sound(0, _unit_hud_shield_damage)); /* The real hit hold survives. */

    network_distributed_note_shield_damage(0, 53);
    assert(distributed_shield_histories[0].hit_pending);
    reset(); /* Uses the production new-game history reset statement. */
    assert(!distributed_shield_histories[0].valid && !distributed_shield_histories[0].hit_pending);
    receive_state(1, packet(0, 3.0f, 0, 0));
    receive_state(2, packet(0, decay(3.0f, 1), 0, 0)); update_hud(0);
    assert(!sound(0, _unit_hud_shield_damage));
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "local_lifecycle")) local_lifecycle();
    else if (!strcmp(argv[1], "local_damage")) local_damage();
    else if (!strcmp(argv[1], "multiple_players")) multiple_players();
    else if (!strcmp(argv[1], "network_passive_decay")) network_passive_decay();
    else if (!strcmp(argv[1], "network_real_damage")) network_real_damage();
    else if (!strcmp(argv[1], "uncertain_network_transitions")) uncertain_network_transitions();
    else if (!strcmp(argv[1], "sentinel_lifecycle")) sentinel_lifecycle();
    else if (!strcmp(argv[1], "network_multiple_players")) network_multiple_players();
    else if (!strcmp(argv[1], "host_timestamps_and_events")) host_timestamps_and_events();
    else assert(0);
    return 0;
}
'''


def production_code():
    damage = (ROOT / "source/objects/damage.c").read_text()
    damage_header = (ROOT / "source/objects/damage.h").read_text()
    hud = (ROOT / "source/interface/hud_unit.c").read_text()
    objects = (ROOT / "source/objects/objects.h").read_text()
    cseries = (ROOT / "source/cseries/cseries.h").read_text()
    network = (ROOT / "port/linux/game/network_distributed.c").read_text()
    network_header = (ROOT / "port/linux/game/network_distributed.h").read_text()
    network_damage = (ROOT / "port/linux/game/network_damage.c").read_text()
    players_header = (ROOT / "source/game/players.h").read_text()
    connection = (ROOT / "source/networking/network_connection.h").read_text()
    hud_header = (ROOT / "source/interface/unit_hud_interface_definition.h").read_text()
    types = "\n".join(re.findall(r"^typedef (?:unsigned char byte|unsigned short word|float real|byte boolean);$",
                                   cseries, re.M))
    types += "\n" + "\n".join(re.findall(r"^#define (?:FLAG|TEST_FLAG|SET_FLAG)\([^\n]*", cseries, re.M))
    for source, name in ((cseries, "TICKS_PER_SECOND"), (connection, "MAXIMUM_NUMBER_OF_LOCAL_PLAYERS"),
                         (network, "GAME_STATE_INTERVAL_TICKS")):
        match = re.search(rf"\b{name}\s*=\s*([^,\n]+)", source)
        types += f"\nenum {{ {name} = {match[1]} }};"
    types += "\n" + re.search(r"^#define VITALITY_SCALE[^\n]+", network, re.M)[0]
    types += "\n" + re.search(r"^#define objects_update_shields[^\n]+", damage, re.M)[0]
    declarations = "\n".join(enum_containing(source, name) for source, name in (
        (objects, "_object_invisible_bit"), (objects, "_object_passed_body_damage_threshold_bit"),
        (damage_header, "_damage_area_of_effect_bit"), (hud, "_hud_panel_health_dont_show_bit"),
        (hud_header, "_unit_hud_shield_recharging"), (players_header, "_player_powerup_active_camouflage"),
        (network, "_distributed_unit_alive_bit"), (network_header, "_distributed_message_player_prediction"),
        (network_damage, "_damage_event_player_effect"),
        (damage_header, "_object_being_damaged_body_depleted_bit")))
    declarations += "\nenum { _object_mask_unit = 1 };"
    declarations += "\n" + "\n".join(block(source, f"struct {name}\n") + ";" for source, name in (
        (damage_header, "damage_network_state"), (hud, "unit_hud_state"), (hud, "unit_hud_globals"),
        (network_header, "distributed_vector"), (network, "distributed_unit_state"),
        (network, "distributed_shield_history"), (network_header, "distributed_message_header")))
    functions = [function(hud, name) for name in (
        "initialize_hud_state", "get_hud_state", "hud_tick_shield", "hud_play_unit_sounds",
        "hud_update_unit_local_player")]
    functions += [function(damage, name) for name in ("object_damage_update", "damage_set_network_state")]
    functions += [function(network, name) for name in ("distributed_vitality_pack", "distributed_vitality_unpack")]
    functions += [function(network, name) for name in (
        "distributed_decay_bound", "distributed_passive_shield_loss", "network_distributed_note_shield_damage")]
    # Keep the actual state reader loop and damage application block. The rest
    # of unit state application (prediction, spawning and seats) is out of scope.
    application = block(network, "{\n\t\tstruct damage_network_state damage;")
    functions.append("static void distributed_handle_unit_state(\n"
                     "struct distributed_unit_state const *state, long host_time) {\n"
                     "long player_index = state->player_index, unit_index = state->unit_index;\n"
                     + application + "\n}")
    functions.append(function(network, "distributed_handle_unit_states"))
    # Keep event validation and aftermath handling while omitting unrelated
    # player-effect/kill cases and their larger game dependencies.
    event_handler = function(network_damage, "network_damage_handle_events")
    before_cases = event_handler.split("case _damage_event_player_effect:", 1)[0]
    aftermath = event_handler.split("case _damage_event_aftermath:", 1)[1].split("case _damage_event_kill:", 1)[0]
    functions.append(before_cases + "case _damage_event_aftermath:" + aftermath + "default: assert(0);\n}\n}\n}")
    dispatcher = function(network, "network_distributed_handle_message")
    cases = dispatcher.rsplit("switch (header.type)", 1)[1]
    state_case = cases.split("case _distributed_message_unit_states:", 1)[1].split(
        "case _distributed_message_player_statistics:", 1)[0]
    event_case = cases.split("case _distributed_message_damage_events:", 1)[1].split(
        "case _distributed_message_hit_reports:", 1)[0]
    functions.append("static void fixture_dispatch(struct distributed_message_header header, "
                     "void const *message, word size) {\n"
                     "void const *entries = (byte const *)message + sizeof(header);\n"
                     "switch (header.type) {\ncase _distributed_message_unit_states:" + state_case +
                     "case _distributed_message_damage_events:" + event_case + "default: assert(0);\n}\n}")
    prototypes = "\n".join(item.split("{", 1)[0].rstrip() + ";" for item in functions)
    declarations += "\n" + prototypes
    history = "static struct distributed_shield_history distributed_shield_histories[MAXIMUM_LOCAL_PLAYERS];"
    reset_history = re.search(r"csmemset\(\s*distributed_shield_histories,\s*0,\s*"
                              r"sizeof\(distributed_shield_histories\)\s*\);", network)[0]
    return tuple(re.sub(r"\blong\b", "int32_t", re.sub(r"\bunsigned\s+long\b", "uint32_t", part))
                 for part in (types, declarations, "\n\n".join(functions), history, reset_history))


class OvershieldHudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="halo-overshield-hud-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        types, declarations, functions, history, reset_history = production_code()
        probe = directory / "overshield_hud.c"
        probe.write_text(PREFIX.replace("/* PRODUCTION TYPES AND CONSTANTS */", types).replace(
            "/* PRODUCTION DECLARATIONS */", declarations).replace(
            "/* PRODUCTION FUNCTIONS */", functions).replace(
            "/* PRODUCTION HISTORY GLOBAL */", history) + HARNESS.replace(
            "/* RESET HISTORY */", reset_history))
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise AssertionError("A C compiler (clang or cc) is required")
        suffix = ".exe" if sys.platform == "win32" else ""
        cls.executable = directory / ("overshield_hud" + suffix)
        command = [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-variable"]
        # Windows runners use MinGW Clang, which has no ASan runtime.
        if sys.platform != "win32":
            command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        math_library = [] if sys.platform == "win32" else ["-lm"]
        command += [str(probe), *math_library, "-o", str(cls.executable)]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def run_case(self, case):
        tested = subprocess.run([str(self.executable), case], capture_output=True, text=True, timeout=10)
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)

    def test_local_charge_and_complete_decay(self):
        self.run_case("local_lifecycle")

    def test_real_local_shield_and_body_hits(self):
        self.run_case("local_damage")

    def test_multiple_local_players_and_remote_unit(self):
        self.run_case("multiple_players")

    def test_network_decay_at_varied_quantized_packet_intervals(self):
        self.run_case("network_passive_decay")

    def test_network_hits_and_mixed_decay_preserve_feedback(self):
        self.run_case("network_real_damage")

    def test_stale_overcharge_respawn_and_large_network_gaps_are_conservative(self):
        self.run_case("uncertain_network_transitions")

    def test_uninitialized_remote_and_non_player_hud_lifecycle(self):
        self.run_case("sentinel_lifecycle")

    def test_network_compensation_is_per_local_player(self):
        self.run_case("network_multiple_players")

    def test_host_timestamps_event_order_and_new_game_reset(self):
        self.run_case("host_timestamps_and_events")


if __name__ == "__main__":
    unittest.main()
