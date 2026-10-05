/* Optional timer recordings, played through the normal SDL mixer. */
#ifndef HALO_PERFORMANCE_AUDIO_H
#define HALO_PERFORMANCE_AUDIO_H

/* Main/game thread only. A complete sounds/performance pack below the game
 * data root takes priority over one below the save root. Partial roots are
 * never combined. Availability is fixed until restart; no files are fetched. */
int halo_performance_audio_available(void);
/* Exact PCM duration rounded up to 30 Hz ticks; zero for unavailable clips. */
long halo_performance_audio_duration_ticks(const char *cue);
/* Mixer completion, independent of delayed host clock snapshots. */
int halo_performance_audio_busy(void);
int halo_performance_audio_play(const char *cue, float volume);
void halo_performance_audio_stop(void);

#endif
