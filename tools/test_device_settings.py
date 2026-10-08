"""Exercise the production menu save boundary with refusing storage/display backends."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "device_settings.h"
#include "port_config.h"
#include "controller_settings.h"
#if defined(HALO_MACOS) && !defined(HALO_IOS)
#define MAC_FULLSCREEN 1
#define MOBILE_FULLSCREEN 0
#define CONFIG_FULLSCREEN 0
#elif defined(HALO_ANDROID) || defined(HALO_IOS)
#define MAC_FULLSCREEN 0
#define MOBILE_FULLSCREEN 1
#define CONFIG_FULLSCREEN 0
#else
#define MAC_FULLSCREEN 0
#define MOBILE_FULLSCREEN 0
#define CONFIG_FULLSCREEN 1
#endif
static const char *names[] = {"audio.volume", "audio.music_volume", "audio.effects_volume",
    "audio.dialogue_volume", "audio.timer_volume", "audio.menu_music", "display.vsync", "display.interpolation",
    "audio.timer_countdown", "audio.timer_beeps", "audio.timer_minutes", "audio.timer_items",
    "display.timer_position", "display.timer_scale", "display.fullscreen",
    "maps.show_og", "maps.show_community", "network.join_in_progress",
    "input.left_stick_deadzone", "input.right_stick_deadzone", "input.look_acceleration",
    "input.fast_menu_repeat", "display.high_res_hud", "game.show_default_game_types"};
#define TEST_SETTING_COUNT (sizeof(names)/sizeof(names[0]))
static double saved[TEST_SETTING_COUNT];
static const char *renderer="angle",*antialiasing="off";
static long render_height=480,frame_limit;
static int fullscreen, native_fullscreen, write_ok, switch_ok, apply_ok, writes, audio_applies, video_applies, switches, starts, stops;
static int write_fail_on, switch_fail_on, apply_fail_on;
static int index_of(const char *name) {
    for (unsigned i=0;i<TEST_SETTING_COUNT;i++) if (!strcmp(names[i],name)) return (int)i;
    assert(!"unknown preference"); return -1;
}
int config_boolean(const char *name) {
    if (!strcmp(name,"display.fullscreen")) assert(CONFIG_FULLSCREEN);
    assert(strcmp(name,"input.fast_menu_repeat"));
    return saved[index_of(name)] != 0;
}
double config_real(const char *name) { return saved[index_of(name)]; }
long config_integer(const char *name) {
    if(!strcmp(name,"display.render_height")) return render_height;
    if(!strcmp(name,"display.frame_limit")) return frame_limit;
    return (long)saved[index_of(name)];
}
const char *config_string(const char *name) {
    if(!strcmp(name,"display.renderer")) return renderer;
    assert(!strcmp(name,"display.anti_aliasing"));return antialiasing;
}
int config_refresh_string(const char *name) { assert(!strcmp(name,"display.renderer"));return 1; }
int config_write_values(const struct config_update *updates,unsigned count) {
    writes++; if (!write_ok || writes==write_fail_on) return 0;
    for (unsigned i=0;i<count;i++) {
        const char *key=updates[i].name;
        if(updates[i].type==_config_update_string) {
            if(!strcmp(key,"display.renderer")) renderer=updates[i].string;
            else { assert(!strcmp(key,"display.anti_aliasing"));antialiasing=updates[i].string; }
            continue;
        }
        if(!strcmp(key,"display.render_height")) { render_height=(long)updates[i].number;continue; }
        if(!strcmp(key,"display.frame_limit")) { frame_limit=(long)updates[i].number;continue; }
        if (!strcmp(key,"display.fullscreen")) assert(CONFIG_FULLSCREEN);
        assert(strcmp(key,"input.fast_menu_repeat"));
        saved[index_of(key)]=updates[i].number;
    }
    return 1;
}
int halo_video_fullscreen_get(void) { return MOBILE_FULLSCREEN ? 1 : fullscreen; }
int halo_video_fullscreen_set(int enabled) {
    switches++;
    if (!switch_ok || switches==switch_fail_on) return 0;
    if (MOBILE_FULLSCREEN) return enabled != 0;
    fullscreen=enabled;
    if (MAC_FULLSCREEN) native_fullscreen=enabled;
    return 1;
}
int halo_video_apply_settings(void) { video_applies++; return apply_ok && video_applies!=apply_fail_on; }
void halo_audio_apply_settings(void) { audio_applies++; }
void ui_apply_main_menu_music_setting(void) { if (saved[5]) starts++; else stops++; }
static void reset(double values[NUMBER_OF_DEVICE_SETTINGS]) {
    for (unsigned i=0;i<TEST_SETTING_COUNT;i++) saved[i]=(i==7 || i==11 || i==12) ? 0.0 : 1.0;
    saved[18]=saved[19]=9000;
    saved[21]=saved[22]=0;
    saved[0]=0.15; fullscreen=native_fullscreen=1; write_ok=switch_ok=apply_ok=1;
    renderer="angle";antialiasing="off";render_height=480;frame_limit=0;
    writes=audio_applies=video_applies=switches=starts=stops=0;
    write_fail_on=switch_fail_on=apply_fail_on=0;
    for(int i=0;i<NUMBER_OF_DEVICE_SETTINGS;i++) values[i]=device_settings_get(i);
}
static void check_controller_settings(double values[NUMBER_OF_DEVICE_SETTINGS]) {
    /* Controller edits persist atomically without touching audio or video;
     * Android and iOS use the same preference boundary as desktop. */
    reset(values);
    assert(values[_device_setting_left_stick_deadzone]==9000 && values[_device_setting_right_stick_deadzone]==9000);
    values[_device_setting_left_stick_deadzone]=0; values[_device_setting_right_stick_deadzone]=16000;
    assert(device_settings_apply((1UL<<_device_setting_left_stick_deadzone)|(1UL<<_device_setting_right_stick_deadzone),values));
    assert(writes==1 && saved[18]==0 && saved[19]==16000 && !audio_applies && !video_applies && !switches);
    reset(values); saved[18]=1234; values[_device_setting_left_stick_deadzone]=1234;
    assert(device_settings_apply(1UL<<_device_setting_left_stick_deadzone,values) && !writes && saved[18]==1234);
    values[_device_setting_left_stick_deadzone]=6553; values[_device_setting_right_stick_deadzone]=3277; write_ok=0;
    assert(!device_settings_apply((1UL<<_device_setting_left_stick_deadzone)|(1UL<<_device_setting_right_stick_deadzone),values));
    assert(saved[18]==1234 && saved[19]==9000 && !audio_applies && !video_applies && !switches);
    reset(values);
    for(int setting=_device_setting_left_stick_deadzone;setting<=_device_setting_right_stick_deadzone;setting++) {
        const double bad[]={-1,16001,0.5,NAN,INFINITY};
        for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
            values[setting]=bad[i]; assert(!device_settings_apply(1UL<<setting,values));
        }
        values[setting]=9000;
    }
    assert(!writes && !audio_applies && !video_applies && !switches);
    saved[18]=-1; saved[19]=16001;
    assert(device_settings_get(_device_setting_left_stick_deadzone)==9000 && device_settings_get(_device_setting_right_stick_deadzone)==9000);
    reset(values);
    assert(values[_device_setting_look_acceleration]==1);
    values[_device_setting_look_acceleration]=0.5;
    assert(!device_settings_apply(1UL<<_device_setting_look_acceleration,values) && !writes);
    values[_device_setting_look_acceleration]=0;
    assert(device_settings_apply(1UL<<_device_setting_look_acceleration,values));
    assert(writes==1 && saved[20]==0 && !audio_applies && !video_applies && !switches);
    values[_device_setting_look_acceleration]=1; values[_device_setting_left_stick_deadzone]=3277; write_ok=0;
    assert(!device_settings_apply((1UL<<_device_setting_look_acceleration)|(1UL<<_device_setting_left_stick_deadzone),values));
    assert(saved[20]==0 && saved[18]==9000 && !audio_applies && !video_applies && !switches);
}
static void check_menu_repeat_settings(double values[NUMBER_OF_DEVICE_SETTINGS]) {
    unsigned long menu_repeat = 1UL << _device_setting_fast_menu_repeat;
    const double ignored[] = {0, 1, -1, 2, 0.5, NAN, INFINITY, -INFINITY};
    reset(values);
    assert(values[_device_setting_fast_menu_repeat]==1 && halo_menu_repeat_milliseconds()==100);
    /* Legacy files and drafts cannot change the fixed cadence or write the
     * retired preference. Keep its ID so old drafts remain harmless. */
    for(int prior=0;prior<2;prior++) {
        saved[21]=prior;
        for(unsigned i=0;i<sizeof(ignored)/sizeof(ignored[0]);i++) {
            values[_device_setting_fast_menu_repeat]=ignored[i];
            assert(device_settings_apply(menu_repeat,values));
            assert(saved[21]==prior && device_settings_get(_device_setting_fast_menu_repeat)==1 &&
                halo_menu_repeat_milliseconds()==100);
        }
    }
    assert(!writes && !audio_applies && !video_applies && !switches && !starts && !stops);
    /* A mixed draft still rolls its live setting back on backend refusal. */
    reset(values);
    values[_device_setting_fast_menu_repeat]=0;
    values[_device_setting_vsync]=0;
    apply_fail_on=1;
    assert(!device_settings_apply(menu_repeat | (1UL<<_device_setting_vsync),values));
    assert(saved[21]==0 && saved[6]==1 && halo_menu_repeat_milliseconds()==100 && writes==2);
}
static void check_game_type_settings(double values[NUMBER_OF_DEVICE_SETTINGS]) {
    unsigned long presets = 1UL << _device_setting_show_default_game_types;
    const double bad[] = {-1, 2, 0.5, NAN, INFINITY, -INFINITY};
    reset(values);
    assert(values[_device_setting_show_default_game_types]==1);
    assert(device_settings_apply(presets,values) && !writes);
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        values[_device_setting_show_default_game_types]=bad[i];
        assert(!device_settings_apply(presets,values));
    }
    assert(!writes);
    values[_device_setting_show_default_game_types]=0;
    write_ok=0;
    assert(!device_settings_apply(presets,values) && saved[23]==1 && writes==1);
    write_ok=1;
    assert(device_settings_apply(presets,values) && saved[23]==0 && writes==2);
    assert(!audio_applies && !video_applies && !switches && !starts && !stops);
    reset(values);values[_device_setting_show_default_game_types]=0;values[_device_setting_vsync]=0;
    apply_fail_on=1;
    assert(!device_settings_apply(presets|(1UL<<_device_setting_vsync),values));
    assert(saved[23]==1 && saved[6]==1 && writes==2 && video_applies==2);
}
static void check_hud_settings(double values[NUMBER_OF_DEVICE_SETTINGS]) {
    unsigned long hud=1UL<<_device_setting_asset_quality;
    const double bad[]={-1,2,0.5,NAN,INFINITY,-INFINITY};
    reset(values);
    assert(values[_device_setting_asset_quality]==0);
    assert(device_settings_apply(hud,values) && !writes);
    for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++) {
        values[_device_setting_asset_quality]=bad[i];
        assert(!device_settings_apply(hud,values));
    }
    assert(!writes && !audio_applies && !video_applies && !switches);
    values[_device_setting_asset_quality]=1;write_ok=0;
    assert(!device_settings_apply(hud,values));
    assert(saved[22]==0 && writes==1);
    write_ok=1;
    assert(device_settings_apply(hud,values));
    assert(saved[22]==1 && device_settings_get(_device_setting_asset_quality)==1 && writes==2);
    /* Texture choice takes effect on relaunch, without live display/audio work. */
    assert(!audio_applies && !video_applies && !switches && !starts && !stops);
    assert(device_settings_apply(hud,values) && writes==2);
    values[_device_setting_asset_quality]=0;
    assert(device_settings_apply(hud,values) && saved[22]==0 && writes==3);
    /* A rejected live video row rolls back the entire saved draft. */
    reset(values);values[_device_setting_asset_quality]=1;values[_device_setting_vsync]=0;
    apply_fail_on=1;
    assert(!device_settings_apply(hud|(1UL<<_device_setting_vsync),values));
    assert(saved[22]==0 && saved[6]==1 && writes==2 && video_applies==2);
}
int main(void) {
    double values[NUMBER_OF_DEVICE_SETTINGS];
    check_controller_settings(values);
    check_menu_repeat_settings(values);
    check_game_type_settings(values);
    check_hud_settings(values);
    if (MOBILE_FULLSCREEN) {
        /* Android/iOS remain fullscreen and never read or persist the
         * desktop-only preference, even in a mixed settings draft. */
        reset(values);
        assert(device_settings_get(_device_setting_fullscreen)==1);
        assert(device_settings_apply(1UL<<_device_setting_fullscreen,values));
        assert(!writes && !switches);
        values[_device_setting_fullscreen]=0; values[0]=0.2;
        assert(!device_settings_apply(1UL | (1UL<<_device_setting_fullscreen),values));
        assert(!writes && switches==1 && saved[0]==0.15 && fullscreen==1);
        puts("mobile fullscreen settings tests passed");
        return 0;
    }
    reset(values);
    /* Opening/saving an untouched page preserves an off-step master volume. */
    assert(device_settings_apply(0,NULL));
    assert(device_settings_apply((1UL<<NUMBER_OF_DEVICE_SETTINGS)-1,values));
    assert(writes==0 && audio_applies==0 && switches==0 && saved[0]==0.15);
    values[_device_setting_music_volume]=0.4; values[_device_setting_menu_music]=0;
    assert(device_settings_apply((1UL<<_device_setting_music_volume)|(1UL<<_device_setting_menu_music),values));
    assert(writes==1 && audio_applies==1 && stops==1 && starts==0 && saved[0]==0.15 && saved[1]==0.4);
    assert(video_applies==0 && switches==0);
    reset(values); values[_device_setting_master_volume]=0; write_ok=0;
    assert(!device_settings_apply(1,values)); assert(saved[0]==0.15 && audio_applies==0);
    reset(values); values[0]=NAN; assert(!device_settings_apply(1,values));
    values[0]=1.1; assert(!device_settings_apply(1,values));
    values[0]=-0.1; assert(!device_settings_apply(1,values));
    values[_device_setting_menu_music]=0.5;
    assert(!device_settings_apply(1UL<<_device_setting_menu_music,values));
    assert(!device_settings_apply(1UL<<NUMBER_OF_DEVICE_SETTINGS,values));
    assert(!device_settings_apply(1,NULL)); assert(writes==0 && switches==0);
    reset(values); values[_device_setting_fullscreen]=0;
    assert(device_settings_apply(1UL<<_device_setting_fullscreen,values));
    assert(!fullscreen && switches==1 && writes==CONFIG_FULLSCREEN);
    assert(saved[14]==(CONFIG_FULLSCREEN ? 0 : 1));
    assert(native_fullscreen==(MAC_FULLSCREEN ? 0 : 1));
    assert(saved[0]==0.15 && !audio_applies && !video_applies);
    reset(values); values[_device_setting_fullscreen]=0; values[_device_setting_vsync]=0;
    switch_ok=0; assert(!device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync),values));
    assert(fullscreen && writes==0 && saved[6]==1 && saved[14]==1 && native_fullscreen==1);
    reset(values); values[_device_setting_fullscreen]=0; values[_device_setting_vsync]=0; write_ok=0;
    assert(!device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync),values));
    assert(fullscreen && switches==2 && saved[6]==1 && saved[14]==1 && native_fullscreen==1 && video_applies==0);
    reset(values); values[_device_setting_fullscreen]=0; values[_device_setting_vsync]=0; apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync),values));
    assert(fullscreen && saved[6]==1 && saved[14]==1 && native_fullscreen==1 && writes==2 && switches==2 && video_applies==2);
    reset(values); values[_device_setting_fullscreen]=0; values[_device_setting_vsync]=0;
    write_ok=0; switch_fail_on=2;
    assert(device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync),values)==-1);
    assert(!fullscreen && saved[6]==1);
    reset(values); values[_device_setting_vsync]=0; apply_fail_on=1; write_fail_on=2;
    assert(device_settings_apply(1UL<<_device_setting_vsync,values)==-1);
    assert(saved[6]==0); /* Report incomplete rollback, never pretend unchanged. */
    reset(values); values[_device_setting_vsync]=0; apply_ok=0;
    assert(device_settings_apply(1UL<<_device_setting_vsync,values)==-1);
    reset(values); values[_device_setting_interpolation]=1;
    assert(device_settings_apply(1UL<<_device_setting_interpolation,values));
    assert(saved[7]==1 && video_applies==1 && audio_applies==0);
    /* A window toggled outside this menu can differ from its saved setting.
     * On failure restore the original file and window independently. Mac's
     * native preference follows its window; its unused TOML value is kept. */
    for (int prior=0;prior<2;prior++) {
        reset(values);
        saved[14]=prior;
        fullscreen=native_fullscreen=!prior;
        values[_device_setting_fullscreen]=prior;
        values[_device_setting_vsync]=0;
        apply_fail_on=1;
        assert(!device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync),values));
        assert(saved[14]==prior && fullscreen==!prior && native_fullscreen==!prior);
        assert(saved[6]==1 && saved[0]==0.15 && writes==2 && switches==2 && video_applies==2);
    }
    reset(values); saved[14]=0;
    values[_device_setting_fullscreen]=0; values[0]=0.2; write_ok=0;
    assert(!device_settings_apply(1UL | (1UL<<_device_setting_fullscreen),values));
    assert(saved[14]==0 && saved[0]==0.15 && fullscreen==1 && native_fullscreen==1 && writes==1 && switches==2);
    reset(values); values[_device_setting_fullscreen]=0;
    values[_device_setting_vsync]=0; values[_device_setting_music_volume]=0.4;
    apply_fail_on=1; write_fail_on=2;
    assert(device_settings_apply((1UL<<_device_setting_fullscreen)|(1UL<<_device_setting_vsync)|(1UL<<_device_setting_music_volume),values)==-1);
    assert(fullscreen==1 && native_fullscreen==1 && saved[14]==(CONFIG_FULLSCREEN ? 0 : 1));
    assert(saved[1]==0.4 && saved[6]==0 && saved[0]==0.15 && audio_applies==1);
    /* New timer preferences do not enable match rules or reconfigure audio/video backends. */
    reset(values);
    assert(values[_device_setting_timer_countdown]==1 && values[_device_setting_timer_beeps]==1 &&
        values[_device_setting_timer_minutes]==1 && values[_device_setting_timer_items]==0 &&
        values[_device_setting_timer_position]==0 && values[_device_setting_timer_scale]==1);
    values[_device_setting_timer_countdown]=0; values[_device_setting_timer_beeps]=0;
    values[_device_setting_timer_minutes]=0; values[_device_setting_timer_items]=1;
    values[_device_setting_timer_position]=2; values[_device_setting_timer_scale]=0.625;
    assert(device_settings_apply(((1UL<<NUMBER_OF_DEVICE_SETTINGS)-1) & ~((1UL<<9)-1),values));
    assert(writes==1 && !audio_applies && !video_applies && !switches && !starts && !stops);
    assert(saved[8]==0 && saved[9]==0 && saved[10]==0 && saved[11]==1 && saved[12]==2 && saved[13]==0.625);
    reset(values);
    for(int setting=_device_setting_timer_countdown;setting<=_device_setting_timer_items;setting++) {
        values[setting]=0.5; assert(!device_settings_apply(1UL<<setting,values)); values[setting]=0;
    }
    values[_device_setting_timer_position]=1.5; assert(!device_settings_apply(1UL<<_device_setting_timer_position,values));
    values[_device_setting_timer_position]=3; assert(!device_settings_apply(1UL<<_device_setting_timer_position,values));
    values[_device_setting_timer_scale]=0.49; assert(!device_settings_apply(1UL<<_device_setting_timer_scale,values));
    values[_device_setting_timer_scale]=1.01; assert(!device_settings_apply(1UL<<_device_setting_timer_scale,values));
    assert(!writes);
    reset(values); values[_device_setting_vsync]=0; values[_device_setting_timer_position]=2; values[_device_setting_timer_scale]=0.55;
    apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_vsync)|(1UL<<_device_setting_timer_position)|(1UL<<_device_setting_timer_scale),values));
    assert(writes==2 && saved[6]==1 && saved[12]==0 && saved[13]==1);
    saved[12]=-1; assert(device_settings_get(_device_setting_timer_position)==0);
    saved[12]=3; assert(device_settings_get(_device_setting_timer_position)==0);
    saved[13]=NAN; assert(device_settings_get(_device_setting_timer_scale)==1);
    saved[13]=0.1; assert(device_settings_get(_device_setting_timer_scale)==0.5);
    saved[13]=2; assert(device_settings_get(_device_setting_timer_scale)==1);
    saved[0]=NAN; assert(device_settings_get(0)==0); saved[0]=-1; assert(device_settings_get(0)==0);
    saved[0]=2; assert(device_settings_get(0)==1);
    /* Every changed field rejects non-finite input before any side effect.
     * Include a valid earlier change so a malformed later row cannot result
     * in a partially saved draft. */
    const double nonfinite[] = {NAN, INFINITY, -INFINITY};
    for (unsigned value=0;value<sizeof(nonfinite)/sizeof(nonfinite[0]);value++) {
        for (int setting=0;setting<NUMBER_OF_DEVICE_SETTINGS;setting++) {
            if (setting==_device_setting_fast_menu_repeat) continue;
            reset(values);
            values[0]=0.2;
            values[setting]=nonfinite[value];
            assert(!device_settings_apply(1UL | (1UL<<setting),values));
            assert(!writes && !switches && !video_applies && !audio_applies && !starts && !stops);
            assert(saved[0]==0.15 && fullscreen==1);
        }
        saved[13]=nonfinite[value];
        assert(device_settings_get(_device_setting_timer_scale)==1.0);
    }
    /* Finite out-of-range file values still clamp instead of taking the
     * non-finite timer fallback, including the largest finite magnitude. */
    saved[13]=-DBL_MAX; assert(device_settings_get(_device_setting_timer_scale)==0.5);
    saved[13]=DBL_MAX; assert(device_settings_get(_device_setting_timer_scale)==1.0);
    saved[13]=0.625; assert(device_settings_get(_device_setting_timer_scale)==0.625);
    /* Map filtering and late joins are local preferences with original
     * defaults. They do not reconfigure audio/video or change match rules. */
    reset(values);
    assert(values[_device_setting_show_og_maps]==1 && values[_device_setting_show_community_maps]==1 &&
        values[_device_setting_join_in_progress]==1);
    values[_device_setting_show_community_maps]=0; values[_device_setting_join_in_progress]=0;
    unsigned long multiplayer=(1UL<<_device_setting_show_community_maps)|(1UL<<_device_setting_join_in_progress);
    assert(device_settings_apply(multiplayer,values));
    assert(writes==1 && saved[15]==1 && saved[16]==0 && saved[17]==0);
    assert(!audio_applies && !video_applies && !switches && !starts && !stops);
    values[_device_setting_show_og_maps]=0;
    assert(!device_settings_apply(1UL<<_device_setting_show_og_maps,values) && writes==1);
    assert(saved[15]==1);
    reset(values); values[_device_setting_show_og_maps]=0; values[_device_setting_show_community_maps]=0;
    values[0]=0.2;
    assert(!device_settings_apply(1UL|(1UL<<_device_setting_show_og_maps)|(1UL<<_device_setting_show_community_maps),values));
    assert(!writes && saved[0]==0.15 && saved[15]==1 && saved[16]==1);
    reset(values); values[_device_setting_show_og_maps]=0; write_ok=0;
    assert(!device_settings_apply(1UL<<_device_setting_show_og_maps,values));
    assert(saved[15]==1 && saved[16]==1 && writes==1);
    reset(values); values[_device_setting_show_og_maps]=0; values[_device_setting_join_in_progress]=0;
    values[_device_setting_vsync]=0; apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_vsync)|(1UL<<_device_setting_show_og_maps)|
        (1UL<<_device_setting_join_in_progress),values));
    assert(writes==2 && saved[6]==1 && saved[15]==1 && saved[16]==1 && saved[17]==1);
#if MAC_FULLSCREEN
    assert(NUMBER_OF_DEVICE_SETTINGS==28);
    reset(values);values[_device_setting_renderer]=1;values[_device_setting_render_height]=0;
    values[_device_setting_frame_limit]=120;values[_device_setting_anti_aliasing]=1;
    assert(device_settings_apply((1UL<<_device_setting_renderer)|(1UL<<_device_setting_render_height)|
        (1UL<<_device_setting_frame_limit)|(1UL<<_device_setting_anti_aliasing),values));
    assert(writes==1 && !video_applies && !switches && !strcmp(renderer,"metal") && !strcmp(antialiasing,"fxaa"));
    assert(!render_height && frame_limit==120 && device_settings_get(_device_setting_renderer)==1);
    /* A live backend refusal restores the entire mixed pending/live batch. */
    reset(values);values[_device_setting_renderer]=1;values[_device_setting_render_height]=2160;
    values[_device_setting_anti_aliasing]=1;values[_device_setting_vsync]=0;apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_renderer)|(1UL<<_device_setting_render_height)|
        (1UL<<_device_setting_anti_aliasing)|(1UL<<_device_setting_vsync),values));
    assert(writes==2 && !strcmp(renderer,"angle") && !strcmp(antialiasing,"off") && render_height==480 && saved[6]==1);
    assert(video_applies==2 && !switches);
    /* Controller/asset preferences and pending Metal choices share one draft.
     * A live video refusal must roll every changed type back together. */
    reset(values);values[_device_setting_renderer]=1;values[_device_setting_frame_limit]=60;
    values[_device_setting_left_stick_deadzone]=3277;values[_device_setting_asset_quality]=1;
    values[_device_setting_vsync]=0;apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_renderer)|(1UL<<_device_setting_frame_limit)|
        (1UL<<_device_setting_left_stick_deadzone)|(1UL<<_device_setting_asset_quality)|
        (1UL<<_device_setting_vsync),values));
    assert(writes==2 && !strcmp(renderer,"angle") && frame_limit==0 && saved[18]==9000 &&
        saved[22]==0 && saved[6]==1 && halo_menu_repeat_milliseconds()==100);
    assert(video_applies==2 && !audio_applies && !switches);
    reset(values);values[_device_setting_renderer]=1;values[_device_setting_anti_aliasing]=1;write_ok=0;
    assert(!device_settings_apply((1UL<<_device_setting_renderer)|(1UL<<_device_setting_anti_aliasing),values));
    assert(writes==1 && !video_applies && !strcmp(renderer,"angle") && !strcmp(antialiasing,"off"));
    reset(values);values[_device_setting_renderer]=1;values[_device_setting_frame_limit]=45;
    assert(!device_settings_apply((1UL<<_device_setting_renderer)|(1UL<<_device_setting_frame_limit),values));
    assert(!writes && !strcmp(renderer,"angle"));
    values[_device_setting_frame_limit]=60;values[_device_setting_render_height]=2880;
    assert(!device_settings_apply((1UL<<_device_setting_frame_limit)|(1UL<<_device_setting_render_height),values));
    assert(!writes);
    reset(values);render_height=720;values[_device_setting_render_height]=device_settings_get(_device_setting_render_height);
    assert(values[_device_setting_render_height]==720);
    assert(device_settings_apply(1UL<<_device_setting_render_height,values) && !writes);
#elif HALO_DEVICE_HAS_RENDER_RESOLUTION
    assert(NUMBER_OF_DEVICE_SETTINGS==25);
#else
    assert(NUMBER_OF_DEVICE_SETTINGS==24);
#endif
    puts("device settings save/apply tests passed");
}
'''


class DeviceSettingsTests(unittest.TestCase):
    def run_save_apply_boundary(self, production_flags, platform_flags=()):
        with tempfile.TemporaryDirectory(prefix="halo-device-settings-") as folder:
            path = Path(folder)
            (path / "test.c").write_text(HARNESS)
            (path / "port_config.h").write_text((ROOT / "port/linux/src/port_config.h").read_text())
            (path / "native_audio.h").write_text("void halo_audio_apply_settings(void);\n")
            (path / "native_video.h").write_text(
                "int halo_video_fullscreen_get(void); int halo_video_fullscreen_set(int);\n"
                "int halo_video_apply_settings(void);\n")
            # Darwin may expose isfinite even in C89. Reproduce the Linux
            # game's C89 math surface on every host without defining a fake
            # replacement that could conceal an unresolved runtime call.
            (path / "c89_math_surface.h").write_text("#include <math.h>\n#undef isfinite\n")
            production = path / "device_settings.o"
            subprocess.run(["clang", *production_flags, *platform_flags, "-Wall", "-Wextra", "-Werror",
                            "-include", str(path / "c89_math_surface.h"),
                            "-I", str(path), "-I", str(ROOT / "port/linux/game"),
                            "-c", str(ROOT / "port/linux/game/device_settings.c"),
                            "-o", str(production)], check=True)
            executable = path / ("test.exe" if sys.platform == "win32" else "test")
            subprocess.run(["clang", "-std=c99", *platform_flags, "-Wall", "-Wextra", "-Werror",
                            "-I", str(path), "-I", str(ROOT / "port/linux/game"),
                            "-iquote", str(ROOT / "port/linux/include"),
                            str(path / "test.c"), str(production),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)

    def test_save_apply_boundary(self):
        self.run_save_apply_boundary(["-std=c99"])

    def test_save_apply_boundary_with_game_c89_headers(self):
        for optimization in ("-O0", "-O2"):
            with self.subTest(optimization=optimization):
                self.run_save_apply_boundary(["-std=gnu89", "-D__STRICT_ANSI__", optimization])

    def test_linux_and_windows_share_hud_save_boundary(self):
        for platform in ("HALO_LINUX", "HALO_WINDOWS"):
            with self.subTest(platform=platform):
                self.run_save_apply_boundary(["-std=gnu89", "-D__STRICT_ANSI__", "-O2"],
                                             ["-D" + platform + "=1"])

    def test_mac_fullscreen_uses_native_preferences(self):
        for renderer in ("0", "1"):
            with self.subTest(native_metal=renderer):
                self.run_save_apply_boundary(["-std=gnu89", "-D__STRICT_ANSI__", "-O2"],
                    ["-DHALO_MACOS=1", "-DHALO_ANDROID=1", "-DHALO_MACOS_NATIVE_METAL=" + renderer])

    def test_mobile_fullscreen_stays_platform_owned(self):
        for platform_flags in (["-DHALO_ANDROID=1"],
                               ["-DHALO_ANDROID=1", "-DHALO_MACOS=1", "-DHALO_IOS=1"]):
            with self.subTest(platform_flags=platform_flags):
                self.run_save_apply_boundary(["-std=gnu89", "-D__STRICT_ANSI__", "-O2"], platform_flags)


if __name__ == "__main__":
    unittest.main()
