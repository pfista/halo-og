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


class LoopingSoundLifetimeTests(unittest.TestCase):
    def test_retired_loop_in_same_millisecond(self):
        check_track_lifetime(MANAGER.read_text())

if __name__ == "__main__":
    unittest.main()
