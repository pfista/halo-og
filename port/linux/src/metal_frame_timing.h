/* Native Metal frame phases and visibility submission checkpoint. */
#ifndef HALO_METAL_FRAME_TIMING_H
#define HALO_METAL_FRAME_TIMING_H

enum halo_metal_frame_mark
{
	HALO_METAL_FRAME_LOOP_START,
	HALO_METAL_FRAME_UPDATE_BEGIN,
	HALO_METAL_FRAME_RENDER_BEGIN,
	HALO_METAL_FRAME_GAME_RENDER_BEGIN,
	HALO_METAL_FRAME_GAME_RENDER_END,
	HALO_METAL_FRAME_RENDER_END,
	HALO_METAL_FRAME_THROTTLE_BEGIN,
	HALO_METAL_FRAME_THROTTLE_END,
	HALO_METAL_FRAME_PRESENT_BEGIN,
	HALO_METAL_FRAME_PRESENT_END,
	HALO_METAL_FRAME_LOOP_END
};

#if defined(HALO_MACOS_NATIVE_METAL) && HALO_MACOS_NATIVE_METAL
/* The renderer gates phase samples with the existing gpu_stats setting. */
void halo_metal_frame_mark(enum halo_metal_frame_mark mark);
/* Submit queued visibility tests before the remainder of an async frame. */
void halo_metal_visibility_checkpoint(void);
#else
#define halo_metal_frame_mark(mark) ((void)0)
#define halo_metal_visibility_checkpoint() ((void)0)
#endif

#endif
