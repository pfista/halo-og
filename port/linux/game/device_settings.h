/* Local application preferences shared by native main and pause menus. */
#ifndef HALO_DEVICE_SETTINGS_H
#define HALO_DEVICE_SETTINGS_H

enum
{
    _device_setting_master_volume,
    _device_setting_music_volume,
    _device_setting_effects_volume,
    _device_setting_dialogue_volume,
    _device_setting_timer_volume,
    _device_setting_menu_music,
    _device_setting_fullscreen,
    _device_setting_vsync,
    _device_setting_interpolation,
    _device_setting_timer_countdown,
    _device_setting_timer_beeps,
    _device_setting_timer_minutes,
    _device_setting_timer_items,
    _device_setting_timer_position,
    _device_setting_timer_scale,
    _device_setting_show_og_maps,
    _device_setting_show_community_maps,
    _device_setting_join_in_progress,
    _device_setting_left_stick_deadzone,
    _device_setting_right_stick_deadzone,
    _device_setting_look_acceleration,
    _device_setting_fast_menu_repeat,
    _device_setting_asset_quality,
#if defined(HALO_MACOS) && !defined(HALO_IOS)
    _device_setting_renderer,
    _device_setting_render_height,
    _device_setting_frame_limit,
    _device_setting_anti_aliasing,
#endif
    NUMBER_OF_DEVICE_SETTINGS
};

/* Volumes are 0..1; switches are 0/1. Timer position is 0..2 and scale .5..1.
 * Stick deadzones are raw integer ranges 0..16000; Xbox is exactly 9000.
 * Mac renderer/AA choices are 0/1; height/cap are their config pixel/FPS values.
 * Asset quality, renderer, render height and AA describe saved choices for the next launch. */
double device_settings_get(short setting);
/* Save only changed rows, then apply to the current session. Returns 1 on
 * success, 0 on failure with prior settings restored, or -1 when a backend
 * also refused restoration (the menu must refresh its displayed values).
 * A zero mask is a successful no-op. Call from the game thread. */
int device_settings_apply(unsigned long changed_mask,
    const double values[NUMBER_OF_DEVICE_SETTINGS]);

#endif
