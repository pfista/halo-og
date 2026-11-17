"""Exercise orphaned loop tracks and detached channels against the production sound manager."""
import unittest

from tools.test_performance_sound import PREFIX, ROOT, compile_run, function


MANAGER = ROOT / "source/sound/sound_manager.c"


def check_track_lifetime(manager):
    compile_run(PREFIX + r'''
enum { _sound_impulse, _sound_loop_track, _sound_delayed_bit };
struct sound_source { int position; };
struct sound_datum {
    short type, playing_channel_index;
    unsigned flags;
    long start_time, source_identifier;
    boolean (*track_proc)(long, void *, struct sound_source *);
    void *track_data;
    struct sound_source source;
};
static struct sound_datum voice;
static struct { long sound_index; } channel;
static struct { boolean speech; } sound_class;
static struct { long render_time; } sound_manager_globals = {100};
static long live_owner;
#define sound_get(index) (&voice)
#define channel_get(index) (&channel)
#define sound_class_get(index) (&sound_class)
#define datum_try_and_get(data, id) ((id) == live_owner)
static boolean track(long owner, void *data, struct sound_source *source) {
    (void)data;
    source->position = 5;
    return owner == live_owner;
}
''' + function(manager, "static boolean refresh_sound(") + r'''
int main(void) {
    live_owner = 0x10002;
    voice = (struct sound_datum){.type = _sound_loop_track, .playing_channel_index = NONE,
        .track_proc = track, .source_identifier = live_owner, .start_time = 100};
    assert(refresh_sound(0) && voice.source.position == 0);
    ++sound_manager_globals.render_time;
    assert(refresh_sound(0) && voice.source.position == 5);

    voice.start_time = sound_manager_globals.render_time;
    live_owner = 0x20002; /* Same slot, different loop. */
    assert(!refresh_sound(0));
    voice.type = _sound_impulse;
    voice.flags = FLAG(_sound_delayed_bit);
    assert(refresh_sound(0));
    return 0;
}
''')


def check_map_teardown(manager):
    compile_run(PREFIX + r'''
struct sample { int references; };
struct sound_channel_datum {
    long sound_index;
    struct sample *playing_permutation, *queued_permutation;
};
static struct sound_channel_datum channels[4];
static unsigned stopped[4];
static void stop_channel(short index) { ++stopped[index]; }
static void set_pause(boolean paused) { assert(!paused); }
static void flush(void) {
    for (short i = 0; i < 4; ++i) {
        assert(!channels[i].playing_permutation && !channels[i].queued_permutation);
    }
}
static struct { void (*stop_channel)(short); void (*set_pause)(boolean); void (*flush)(void); } platform = {
    stop_channel, set_pause, flush
};
static struct {
    boolean initialized, enabled, paused;
    short channel_count;
    long render_time, game_time_when_no_scripted_dialog_will_be_playing;
    __typeof__(platform) *platform_definition;
} sound_manager_globals = {.initialized = TRUE, .paused = TRUE, .channel_count = 4,
    .platform_definition = &platform};
static int looping_sound_data = 1;
#define channel_get(index) (&channels[index])
#define data_next_index(data, id) ((id) == NONE ? channels[0].sound_index : NONE)
#define data_delete_all(data) ((void)0)
#define system_milliseconds() 100
#define sound_idle() ((void)0)
#define sound_start_fade(...) ((void)0)
static void sound_cache_sound_finished(struct sample *sample) {
    assert(sample->references > 0);
    --sample->references;
}
''' + function(manager, "static void channel_stop(") + r'''
/* The fixture has one live voice, attached to channel 0. */
static void sound_stop(long index) {
    assert(index == channels[0].sound_index);
    channel_stop(0);
    channels[0].sound_index = NONE;
}
''' + function(manager, "static void sound_stop_all_internal(") +
                function(manager, "void sound_dispose_from_old_map(") + r'''
int main(void) {
    struct sample shared = {3}, queued = {1};
    channels[0] = (struct sound_channel_datum){1, &shared, NULL};
    channels[1] = (struct sound_channel_datum){NONE, &shared, &queued};
    channels[2] = (struct sound_channel_datum){NONE, NULL, &shared};
    channels[3] = (struct sound_channel_datum){NONE, NULL, NULL};
    sound_dispose_from_old_map();
    assert(shared.references == 0 && queued.references == 0);
    sound_dispose_from_old_map();
    for (short i = 0; i < 4; ++i) {
        assert(stopped[i] == (i < 3));
        assert(channels[i].sound_index == NONE);
        assert(!channels[i].playing_permutation && !channels[i].queued_permutation);
    }
    return 0;
}
''')


class LoopingSoundLifetimeTests(unittest.TestCase):
    def test_retired_loop_in_same_millisecond(self):
        check_track_lifetime(MANAGER.read_text())

    def test_map_releases_owned_and_detached_channels_once(self):
        check_map_teardown(MANAGER.read_text())


if __name__ == "__main__":
    unittest.main()
