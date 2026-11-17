"""Spin a simulated Halo OG player through a full turn during throws and jumps."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.test_weapon_sound_events import definition, enum_containing

ROOT = Path(__file__).resolve().parents[1] / "source"

FIXTURE = r'''
#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#include <strings.h>
#define _stricmp strcasecmp
#endif
typedef int boolean;
typedef float real;
typedef struct { real i, j; } real_vector2d;
typedef struct { real i, j, k; } real_vector3d;
typedef struct { real x0, x1, y0, y1; } real_rectangle2d;
#define TRUE 1
#define FALSE 0
#define NONE (-1)
#define _pi 3.14159265358979323846f
#define _real_epsilon 0.0001f
#define square_root sqrtf
#define FLAG(b) (1UL << (b))
#define TEST_FLAG(f,b) ((f) & FLAG(b))
#define match_assert(file,line,condition) assert(condition)

/* GAME ENUMS AND MATH */
struct unit_animation_update_data { int state_desired; };
static struct biped_definition {
    struct { unsigned flags; } unit;
    struct { unsigned flags; real moving_turning_speed, runtime_cosine_stationary_turning_threshold,
        flying_bank_amount, flying_pitch_amount, flying_angular_velocity, flying_angular_acceleration,
        flying_bank_decay_time, flying_bank_apply_time; } biped;
} model;
static struct biped_datum {
    long definition_index;
    struct { real bank; int state; } biped;
    struct { real_vector3d forward, up, translational_velocity, angular_velocity; unsigned damage_flags; } object;
    struct { struct { int state, base_seat_index; } animation;
        real_vector3d throttle, desired_facing_vector; int player_index; unsigned control_flags, flags; } unit;
} actor;
static real_vector3d up_axis = {0, 0, 1};
#define global_up3d (&up_axis)
#define biped_get(index) (&actor)
#define biped_definition_get(index) (&model)
#define biped_verify_object_vectors(index,where) ((void)0)
#define biped_snap_facing(index) abort()
#define unit_euler_aiming_update(...) abort()
#define rotate_vector_about_axis(...) abort()
static unsigned long match_flags;
static const char *asset;
#define tag_get_name(index) asset
#define performance_options_get_flags() match_flags
/* PRODUCTION */

static void spin(int animation, int locomotion, int owner, const char *path, unsigned long rules,
                 unsigned long controls, unsigned long authored_flags, boolean follows)
{
    struct unit_animation_update_data update = {0};
    memset(&actor, 0, sizeof(actor));
    actor.object.forward.i = 1;
    actor.object.up = up_axis;
    actor.unit.animation.base_seat_index = _unit_base_seat_stand;
    actor.unit.animation.state = animation;
    actor.biped.state = locomotion;
    actor.unit.player_index = owner;
    actor.unit.control_flags = controls;
    asset = path;
    match_flags = rules;
    model.biped.flags = authored_flags;
    model.biped.moving_turning_speed = 540.f * _pi / 180.f;
    for (int tick = 1; tick <= 30; ++tick) {
        real yaw = tick * 12.f * _pi / 180.f;
        actor.unit.desired_facing_vector = (real_vector3d){cosf(yaw), sinf(yaw), 0.f};
        biped_update_turning(0, &update);
        assert(fabsf(actor.object.forward.i - (follows ? cosf(yaw) : 1.f)) < 0.0001f);
        assert(fabsf(actor.object.forward.j - (follows ? sinf(yaw) : 0.f)) < 0.0001f);
    }
}
int main(void)
{
    const unsigned long rule = _performance_option_turn_with_aim;
    const char *player = "characters\\cyborg_mp\\CYBORG_MP";
    int states[] = {_unit_state_throw_grenade, _unit_state_airborne};
    for (int i = 0; i < 2; ++i) {
        int state = states[i];
        spin(state, biped_state_unknown, 0, player, rule, 0, 0, TRUE);
        spin(state, biped_state_unknown, 1, "cyborg", rule, 0, 0, TRUE);
        spin(state, biped_state_unknown, 0, player, 0, 0, 0, FALSE);
        spin(state, biped_state_unknown, NONE, player, rule, 0, 0, FALSE);
        spin(state, biped_state_unknown, 0, "marine", rule, 0, 0, FALSE);
        spin(state, biped_state_unknown, 0, player, rule, FLAG(_unit_control_look_dont_turn_bit), 0, FALSE);
    }
    spin(_unit_state_melee_airborne, biped_state_unknown, 1, player, rule, 0, 0, FALSE);
    spin(_unit_state_idle, biped_state_idle, 1, player, rule, 0, 0, FALSE);
    spin(_unit_state_move_front, biped_state_moving, 1, player, 0, 0, 0, TRUE);
    spin(_unit_state_idle, biped_state_idle, NONE, "marine", 0, 0, FLAG(_biped_turns_without_animating_bit), TRUE);
}
'''


class BipedTurnTests(unittest.TestCase):
    def test_spin_during_throw_and_jump(self):
        sources = (
            ("units/bipeds.c", ["biped_state_idle = 0"]),
            ("units/biped_definitions.h", ["_biped_turns_without_animating_bit"]),
            ("units/unit_definitions.h", ["_unit_is_special_bit"]),
            ("units/units.h", ["_unit_state_airborne", "_unit_base_seat_asleep", "_unit_control_look_dont_turn_bit",
                               "_unit_aim_without_turning_bit"]),
            ("objects/objects.h", ["_object_dead_bit"]),
            ("cseries/cseries.h", ["SECONDS_PER_MINUTE"]),
            ("game/performance_variant.h", ["_performance_option_turn_with_aim"]),
        )
        declarations = [enum_containing((ROOT / path).read_text(), name) for path, names in sources for name in names]
        math_header = (ROOT / "math/real_math.h").read_text()
        for result, function in [
            ("real_vector2d *", "scale_vector2d"), ("real_vector2d *", "rotate_vector2d"),
            ("real ", "magnitude_squared2d"), ("real ", "magnitude2d"), ("real ", "normalize2d"),
            ("real ", "dot_product2d"), ("real ", "cross_product2d"), ("real_vector3d *", "scale_vector3d"),
            ("real ", "magnitude_squared3d"), ("real ", "magnitude3d"), ("real ", "normalize3d"),
            ("real ", "dot_product3d"), ("real_vector3d *", "cross_product3d"),
        ]:
            declarations.append(definition(math_header, f"__inline {result}{function}(").replace("__inline", "static", 1))
        production = definition((ROOT / "tag_files/tag_files.c").read_text(), "const char *tag_name_strip_path(")
        production += "\n" + definition((ROOT / "units/bipeds.c").read_text(), "static void biped_update_turning(")
        fixture = FIXTURE.replace("/* GAME ENUMS AND MATH */", "\n".join(declarations))
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "spin.c"
            source.write_text(fixture.replace("/* PRODUCTION */", production))
            binary = source.with_suffix(".exe" if sys.platform == "win32" else "")
            cmd = [shutil.which("clang") or "cc", "-std=c11", "-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=128",
                   str(source), "-o", str(binary)]
            if sys.platform != "win32":
                cmd.append("-lm")
            subprocess.run(cmd, check=True, timeout=30)
            subprocess.run([str(binary)], check=True, timeout=10)
