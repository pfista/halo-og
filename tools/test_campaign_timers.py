"""Campaign waits count 30 Hz game ticks, whatever the frame rate.

The checkpoint wait and the death timers come from production `main.c`. The
game clock, the safety test and the save itself are stubs.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_performance_variants import block

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "source/main/main.c"


def function(source, signature):
    return block(source[source.rindex(signature):], signature)


PREFIX = r'''
#include <assert.h>
#include <stdarg.h>
typedef unsigned char boolean;
#define TRUE 1
#define FALSE 0
#define MIN(a,b) ((a)<(b) ? (a) : (b))
static struct {
    boolean saving_map,save_map_safely,save_map_timeout,save_map_completed;
    long ticks_until_next_save_check,ticks_unable_to_save;
    short safe_intervals;
} main_globals;
static long tick,main_save_last_tick;
static boolean paused,safe,debug_game_save;
static int saves,looks;
static long game_time_get(void) { return tick; }
static boolean game_time_get_paused(void) { return paused; }
static boolean game_safe_to_save(void) { looks++;return safe; }
static void hud_autosave(boolean show) { assert(show);saves++; }
static void console_printf(boolean clear,const char *format,...) { (void)clear;(void)format; }
'''

HARNESS = r'''
static void reset(long start) {
    main_globals.saving_map=FALSE;main_globals.save_map_completed=FALSE;
    tick=start;paused=FALSE;safe=TRUE;saves=0;looks=0;
}
/* Calls the wait `frames` times in every `ticks` game ticks and returns the tick it ended on. */
static long wait_from(long start,int frames,int ticks,long limit) {
    while (main_globals.saving_map && tick<start+limit) {
        for (int frame=0;frame<frames && main_globals.saving_map;frame++) main_save_map_private();
        if (main_globals.saving_map) tick+=ticks;
    }
    return tick;
}
int main(void) {
    static const int paces[][2]={{1,1},{2,1},{4,1},{8,1},{1,2},{1,3}};
    for (unsigned pace=0;pace<sizeof(paces)/sizeof(paces[0]);pace++) {
        int frames=paces[pace][0],ticks=paces[pace][1];
        long ended;

        /* Safe throughout: four looks ten ticks apart, so the save is 33 ticks after the request. */
        reset(100);main_save_map_safe();
        ended=wait_from(100,frames,ticks,2000);
        assert(saves==1 && looks==4 && main_globals.save_map_completed);
        assert(ended>=133 && ended<133+ticks);
        assert(main_globals.ticks_unable_to_save==34);

        /* Never safe: the wait gives up 240 ticks after the request. */
        reset(100);safe=FALSE;main_save_map_safe();
        ended=wait_from(100,frames,ticks,2000);
        assert(!saves && !main_globals.saving_map && !main_globals.save_map_completed);
        assert(ended>=340 && ended<340+ticks);

        /* Without a timeout it keeps waiting, then saves once it has been safe long enough. */
        reset(100);safe=FALSE;main_save_map_no_timeout();
        ended=wait_from(100,frames,ticks,900);
        assert(main_globals.saving_map && !saves);
        safe=TRUE;
        (void)wait_from(tick,frames,ticks,200);
        assert(saves==1 && !main_globals.saving_map);
    }

    /* The first look is on the first wait after the request, and one unsafe look starts the count again. */
    reset(100);main_save_map_safe();
    main_save_map_private();
    assert(looks==1 && main_globals.safe_intervals==1);
    for (int i=0;i<8;i++) main_save_map_private();
    assert(looks==1 && main_globals.ticks_unable_to_save==1);   /* the same tick drawn eight more times */
    tick+=11;main_save_map_private();assert(looks==2 && main_globals.safe_intervals==2);
    safe=FALSE;tick+=11;main_save_map_private();assert(looks==3 && !main_globals.safe_intervals);
    safe=TRUE;
    assert(wait_from(tick,1,1,2000)==122+11*4 && saves==1);

    /* A paused game does not count, and a clock that went backwards counts nothing. */
    reset(100);safe=FALSE;main_save_map_safe();
    main_save_map_private();assert(main_globals.ticks_unable_to_save==1);
    paused=TRUE;tick=105;main_save_map_private();assert(main_globals.ticks_unable_to_save==1);
    paused=FALSE;main_save_map_private();assert(main_globals.ticks_unable_to_save==6);
    tick=40;main_save_map_private();assert(main_globals.ticks_unable_to_save==6 && main_globals.saving_map);
    tick=41;main_save_map_private();assert(main_globals.ticks_unable_to_save==7);

    /* A save that is not asked to be safe happens at once. */
    reset(100);safe=FALSE;main_save_map_safe();main_globals.save_map_safely=FALSE;
    main_save_map_private();assert(saves==1 && !looks && !main_globals.saving_map);

    /* The death timers expire on the 92nd tick at any frame rate. */
    for (int frames=1;frames<=8;frames*=2) {
        short timer=0;long last=tick=500;boolean expired=FALSE;
        while (!expired) {
            tick++;
            for (int frame=0;frame<frames && !expired;frame++) expired=main_death_timer_expired(&timer,&last,TRUE);
        }
        assert(tick==592 && timer==92);
    }
    {
        short timer=0;long last=tick=500;
        tick=520;assert(!main_death_timer_expired(&timer,&last,TRUE) && timer==20);
        /* Ticks that pass while it may not advance are not counted later. */
        tick=560;assert(!main_death_timer_expired(&timer,&last,FALSE) && timer==20);
        tick=561;assert(!main_death_timer_expired(&timer,&last,TRUE) && timer==21);
        /* A loaded checkpoint starts the timer again. */
        tick=300;assert(!main_death_timer_expired(&timer,&last,TRUE) && !timer);
        /* A long blocked respawn stays expired instead of wrapping. */
        tick=300+100000;assert(main_death_timer_expired(&timer,&last,TRUE) && timer==92);
        tick+=100000;assert(main_death_timer_expired(&timer,&last,TRUE) && timer==92);
    }
    return 0;
}
'''


@unittest.skipUnless(shutil.which("clang") or shutil.which("cc"), "C compiler required")
class CampaignTimerTests(unittest.TestCase):
    def test_checkpoint_wait_and_death_timers_count_game_ticks(self):
        source = MAIN.read_text()
        production = "\n".join(function(source, signature) for signature in (
            "void main_save_map_safe(",
            "void main_save_map_no_timeout(",
            "static void main_save_map_private(",
            "static boolean main_death_timer_expired(",
        ))
        compiler = shutil.which("clang") or shutil.which("cc")
        with tempfile.TemporaryDirectory(prefix="halo-campaign-timers-") as folder:
            harness = Path(folder) / "harness.c"
            harness.write_text(PREFIX + production + HARNESS)
            executable = Path(folder) / "timers"
            compiled = subprocess.run([compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                                       "-Wno-unused-function", "-Wno-unused-variable",
                                       "-fsanitize=address,undefined", "-fno-sanitize-recover=undefined",
                                       str(harness), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
