#include "performance_sound.h"
#include "halo_port_capacity.h"
#include <stddef.h>
#include <string.h>

struct performance_sound_provenance
{
	long datum_index;
	unsigned role;
	long player_index;
};

/* Sound manager's fixed pool is 0x200. Effects and particles use the same
 * capacities as their native game pools. A full salted handle distinguishes
 * reused slots; every successful allocation writes even the normal role. */
static struct performance_sound_provenance voices[0x200];
static struct performance_sound_provenance effects[HALO_PORT_MAXIMUM_EFFECTS];
static struct performance_sound_provenance particles[HALO_PORT_MAXIMUM_PARTICLES];
static struct performance_sound_scope current = { _performance_sound_normal, -1 };
static struct performance_sound_statistics statistics;

static struct performance_sound_provenance *provenance_table(unsigned owner, size_t *count)
{
	switch (owner)
	{
		case _performance_sound_voice: *count = sizeof(voices) / sizeof(*voices); return voices;
		case _performance_sound_effect: *count = sizeof(effects) / sizeof(*effects); return effects;
		case _performance_sound_particle: *count = sizeof(particles) / sizeof(*particles); return particles;
		default: *count = 0; return NULL;
	}
}

static struct performance_sound_provenance *provenance_get(unsigned owner, long datum_index)
{
	size_t count;
	struct performance_sound_provenance *table = provenance_table(owner, &count);
	unsigned slot = (unsigned long)datum_index & 0xffffu;
	return datum_index != -1 && slot < count ? &table[slot] : NULL;
}

struct performance_sound_scope performance_sound_push(unsigned role, long player_index)
{
	struct performance_sound_scope previous = current;
	current.role = role & (_performance_sound_movement | _performance_sound_weapon_ready);
	current.player_index = current.role ? player_index : -1;
	return previous;
}

struct performance_sound_scope performance_sound_push_recorded(unsigned owner, long datum_index)
{
	return performance_sound_push(performance_sound_role(owner, datum_index),
		performance_sound_player(owner, datum_index));
}

void performance_sound_pop(struct performance_sound_scope previous)
{
	current = previous;
}

unsigned performance_sound_current(void)
{
	return current.role;
}

long performance_sound_current_player(void)
{
	return current.player_index;
}

void performance_sound_reset(unsigned owner)
{
	size_t count;
	struct performance_sound_provenance *table = provenance_table(owner, &count);
	if (table)
		memset(table, 0, count * sizeof(*table));
	if (owner == _performance_sound_voice)
	{
		memset(&statistics, 0, sizeof(statistics));
		statistics.last_voice_index = statistics.last_definition_index = -1;
		current.role = _performance_sound_normal;
		current.player_index = -1;
	}
}

void performance_sound_record(unsigned owner, long datum_index, unsigned role, long player_index)
{
	struct performance_sound_provenance *record = provenance_get(owner, datum_index);
	if (record)
	{
		record->datum_index = datum_index;
		record->role = role & (_performance_sound_movement | _performance_sound_weapon_ready);
		record->player_index = record->role ? player_index : -1;
		if (owner == _performance_sound_voice)
		{
			if (!record->role) ++statistics.voices_by_role[_performance_sound_normal];
			if (record->role & _performance_sound_movement) ++statistics.voices_by_role[_performance_sound_movement];
			if (record->role & _performance_sound_weapon_ready) ++statistics.voices_by_role[_performance_sound_weapon_ready];
			statistics.last_voice_index = datum_index;
			statistics.last_definition_index = -1;
			statistics.last_voice_role = record->role;
		}
		else if (record->role && owner == _performance_sound_effect) ++statistics.tagged_effects;
		else if (record->role && owner == _performance_sound_particle) ++statistics.tagged_particles;
	}
}

void performance_sound_capture(unsigned owner, long datum_index)
{
	performance_sound_record(owner, datum_index, current.role, current.player_index);
}

void performance_sound_capture_voice(long sound_index, long definition_index)
{
	performance_sound_capture(_performance_sound_voice, sound_index);
	if (provenance_get(_performance_sound_voice, sound_index))
		statistics.last_definition_index = definition_index;
}

void performance_sound_forget(unsigned owner, long datum_index)
{
	struct performance_sound_provenance *record = provenance_get(owner, datum_index);
	if (record && record->datum_index == datum_index)
	{
		record->role = _performance_sound_normal;
		record->player_index = -1;
	}
}

unsigned performance_sound_role(unsigned owner, long datum_index)
{
	struct performance_sound_provenance *record = provenance_get(owner, datum_index);
	return record && record->datum_index == datum_index ? record->role : _performance_sound_normal;
}

long performance_sound_player(unsigned owner, long datum_index)
{
	struct performance_sound_provenance *record = provenance_get(owner, datum_index);
	return record && record->datum_index == datum_index && record->role ? record->player_index : -1;
}

float performance_sound_gain(long sound_index, unsigned silent_roles, unsigned self_roles, long listener_player_index)
{
	unsigned role = performance_sound_role(_performance_sound_voice, sound_index);
	long player_index = performance_sound_player(_performance_sound_voice, sound_index);
	unsigned muted = role & silent_roles;
	/* Unknown ownership must never expose a self-only event to another player.
	 * Equality uses the full salted handles; spatial proximity is irrelevant. */
	if (player_index == -1 || listener_player_index != player_index)
		muted |= role & self_roles;
	if (muted & _performance_sound_movement) ++statistics.muted_dispatches_by_role[_performance_sound_movement];
	if (muted & _performance_sound_weapon_ready) ++statistics.muted_dispatches_by_role[_performance_sound_weapon_ready];
	return muted ? 0.0f : 1.0f;
}

void performance_sound_get_statistics(struct performance_sound_statistics *result)
{
	if (result) *result = statistics;
}
