/* The menus edit a local draft. This is their shared save/apply boundary. */
#include "device_settings.h"
#include "port_config.h"
#include "../include/controller_settings.h"
#include "native_video.h"
#include "native_audio.h"
#include <float.h>
#include <stddef.h>
#include <string.h>

/* Main menu music is controlled on the game thread, never the mixer thread. */
void ui_apply_main_menu_music_setting(void);

static const char *const setting_names[NUMBER_OF_DEVICE_SETTINGS] =
{
    "audio.volume", "audio.music_volume", "audio.effects_volume",
    "audio.dialogue_volume", "audio.timer_volume", "audio.menu_music",
#if defined(HALO_MACOS) || defined(HALO_ANDROID) || defined(HALO_IOS)
    /* Mac owns this in native preferences; mobile has no windowed mode. */
    NULL,
#else
    "display.fullscreen",
#endif
    "display.vsync", "display.interpolation",
    "audio.timer_countdown", "audio.timer_beeps", "audio.timer_minutes", "audio.timer_items",
    "display.timer_position", "display.timer_scale",
    "maps.show_og", "maps.show_community", "network.join_in_progress",
    "input.left_stick_deadzone", "input.right_stick_deadzone", "input.look_acceleration",
    "input.fast_menu_repeat", "display.high_res_hud"
#if defined(HALO_MACOS) && !defined(HALO_IOS)
    , "display.renderer", "display.render_height", "display.frame_limit", "display.anti_aliasing"
#endif
};

static int device_setting_is_finite(double value)
{
    /* Game units use C89 headers, which need not expose C99's isfinite.
     * Ordered comparisons reject NaN as well as either infinity. */
    return value >= -DBL_MAX && value <= DBL_MAX;
}

double device_settings_get(short setting)
{
    double value;
    if (setting < 0 || setting >= NUMBER_OF_DEVICE_SETTINGS) return 0.0;
#if defined(HALO_MACOS) && !defined(HALO_IOS)
    if (setting == _device_setting_renderer)
    {
        config_refresh_string(setting_names[setting]);
        return !strcmp(config_string(setting_names[setting]), "metal");
    }
    if (setting == _device_setting_anti_aliasing) return !strcmp(config_string(setting_names[setting]), "fxaa");
    if (setting == _device_setting_render_height)
    {
        long height = config_integer(setting_names[setting]);
        return height == 0 || height == 480 || height == 720 || height == 1080 || height == 1440 || height == 2160 ? height : 480;
    }
    if (setting == _device_setting_frame_limit)
    {
        long cap = config_integer(setting_names[setting]);
        return cap == 0 || cap == 30 || cap == 60 || cap == 120 ? cap : 0;
    }
#endif
    if (setting == _device_setting_fullscreen) return halo_video_fullscreen_get() != 0;
    if (setting == _device_setting_timer_position)
    {
        long position = config_integer(setting_names[setting]);
        return position >= 0 && position <= 2 ? position : 0;
    }
    if (setting == _device_setting_timer_scale)
    {
        value = config_real(setting_names[setting]);
        return !device_setting_is_finite(value) ? 1.0 : value < 0.5 ? 0.5 : value > 1.0 ? 1.0 : value;
    }
    if (setting == _device_setting_left_stick_deadzone || setting == _device_setting_right_stick_deadzone)
        return halo_controller_deadzone(config_integer(setting_names[setting]));
    if (setting >= _device_setting_menu_music) return config_boolean(setting_names[setting]) != 0;
    value = config_real(setting_names[setting]);
    /* Keep malformed file values out of slider indices. */
    return !(value >= 0.0) ? 0.0 : value > 1.0 ? 1.0 : value;
}

int device_settings_apply(unsigned long changed_mask,
    const double values[NUMBER_OF_DEVICE_SETTINGS])
{
    struct config_update updates[NUMBER_OF_DEVICE_SETTINGS], previous[NUMBER_OF_DEVICE_SETTINGS];
    double old_fullscreen = 0.0;
    unsigned count = 0;
    unsigned long effective = 0;
    int setting, fullscreen_changed = 0;

    if (changed_mask & ~((1UL << NUMBER_OF_DEVICE_SETTINGS) - 1)) return 0;
    if (!changed_mask) return 1;
    if (!values) return 0;
    /* A local map-selection preference must retain at least one enabled set.
     * Unchanged rows come from the current config, not the caller's draft. */
    if (changed_mask & ((1UL << _device_setting_show_og_maps) | (1UL << _device_setting_show_community_maps)))
    {
        double og = changed_mask & (1UL << _device_setting_show_og_maps) ?
            values[_device_setting_show_og_maps] : device_settings_get(_device_setting_show_og_maps);
        double community = changed_mask & (1UL << _device_setting_show_community_maps) ?
            values[_device_setting_show_community_maps] : device_settings_get(_device_setting_show_community_maps);
        if (og == 0.0 && community == 0.0) return 0;
    }
    for (setting = 0; setting < NUMBER_OF_DEVICE_SETTINGS; setting++)
    {
        double old;
        if (!(changed_mask & (1UL << setting))) continue;
        if (!device_setting_is_finite(values[setting])) return 0;
#if defined(HALO_MACOS) && !defined(HALO_IOS)
        if (setting == _device_setting_render_height)
        {
            double height = values[setting];
            if (height != 0.0 && height != 480.0 && height != 720.0 && height != 1080.0 && height != 1440.0 && height != 2160.0) return 0;
        }
        else if (setting == _device_setting_frame_limit)
        {
            double cap = values[setting];
            if (cap != 0.0 && cap != 30.0 && cap != 60.0 && cap != 120.0) return 0;
        }
        else
#endif
        if (setting == _device_setting_timer_position)
        {
            if (values[setting] < 0.0 || values[setting] > 2.0 || values[setting] != (int)values[setting]) return 0;
        }
        else if (setting == _device_setting_timer_scale)
        {
            if (values[setting] < 0.5 || values[setting] > 1.0) return 0;
        }
        else if (setting == _device_setting_left_stick_deadzone || setting == _device_setting_right_stick_deadzone)
        {
            if (values[setting] < 0.0 || values[setting] > HALO_CONTROLLER_DEADZONE_MAX ||
                values[setting] != (int)values[setting]) return 0;
        }
        else if (values[setting] < 0.0 || values[setting] > 1.0 ||
            (setting >= _device_setting_menu_music && values[setting] != 0.0 && values[setting] != 1.0)) return 0;
        old = device_settings_get((short)setting);
        if (old == values[setting]) continue;
        effective |= 1UL << setting;
        if (setting == _device_setting_fullscreen)
        {
            old_fullscreen = old;
            if (!setting_names[setting]) continue;
            /* F11 or a launch override can make the window differ from its
             * saved preference. Roll each back to its own previous value. */
            old = config_boolean(setting_names[setting]) != 0;
        }
        updates[count].name = setting_names[setting];
        updates[count].type = _config_update_number;
        updates[count].number = values[setting];
        updates[count].string = NULL;
        previous[count] = updates[count];previous[count].number = old;
#if defined(HALO_MACOS) && !defined(HALO_IOS)
        if (setting == _device_setting_renderer || setting == _device_setting_anti_aliasing)
        {
            updates[count].type = previous[count].type = _config_update_string;
            previous[count].string = config_string(setting_names[setting]);
            updates[count].string = setting == _device_setting_renderer ?
                (values[setting] != 0.0 ? "metal" : "angle") : (values[setting] != 0.0 ? "fxaa" : "off");
        }
        else if (setting == _device_setting_render_height || setting == _device_setting_frame_limit)
            previous[count].number = config_integer(setting_names[setting]);
#endif
        count++;
    }
    if (!effective) return 1;

    /* Apply fullscreen first so a refused window transition cannot leave
     * any preferences accepted. Mac's setter persists its native preference;
     * other desktops save fullscreen in the same TOML batch as the draft. */
    if (effective & (1UL << _device_setting_fullscreen))
    {
        if (!halo_video_fullscreen_set(values[_device_setting_fullscreen] != 0.0)) return 0;
        fullscreen_changed = 1;
    }
    if (count && !config_write_values(updates, count))
    {
        if (fullscreen_changed && !halo_video_fullscreen_set(old_fullscreen != 0.0)) return -1;
        return 0;
    }
    if ((effective & ((1UL << _device_setting_vsync) | (1UL << _device_setting_interpolation))) &&
        !halo_video_apply_settings())
    {
        /* Restore the accepted preference if the display backend refuses it. */
        int restored = !count || config_write_values(previous, count);
        int video_restored = halo_video_apply_settings();
        int fullscreen_restored = !fullscreen_changed || halo_video_fullscreen_set(old_fullscreen != 0.0);
        if (!restored)
        {
            /* A second storage failure can leave the accepted file in place.
             * Keep audio aligned with that file and report the partial result. */
            if (effective & ((1UL << _device_setting_menu_music) - 1)) halo_audio_apply_settings();
            if (effective & (1UL << _device_setting_menu_music)) ui_apply_main_menu_music_setting();
        }
        return restored && video_restored && fullscreen_restored ? 0 : -1;
    }
    if (effective & ((1UL << _device_setting_menu_music) - 1)) halo_audio_apply_settings();
    if (effective & (1UL << _device_setting_menu_music))
        ui_apply_main_menu_music_setting();
    return 1;
}
