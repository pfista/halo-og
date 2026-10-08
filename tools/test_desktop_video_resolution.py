"""CPU checks for desktop render resolution, settings persistence and resize cleanup."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from tools.test_device_settings import HARNESS as SETTINGS_HARNESS
from tools.test_audio_settings import CONFIG_HARNESS
from tools.test_input_bindings import PREFIX, PORT, ROOT, SDL


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    index = opening + 1
    while depth:
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    return source[start:index]


SETTINGS_MAIN = r'''
int main(void) {
    double values[NUMBER_OF_DEVICE_SETTINGS];
#if HALO_DEVICE_HAS_RENDER_RESOLUTION
    const long heights[]={0,480,720,1080,1440,2160};
    unsigned i;
    for(i=0;i<sizeof(heights)/sizeof(heights[0]);i++) {
        reset(values);values[_device_setting_render_height]=heights[i];
        assert(device_settings_apply(1UL<<_device_setting_render_height,values));
        assert(render_height==heights[i] && !video_applies && !switches && !audio_applies);
    }
    reset(values);values[_device_setting_render_height]=1080;write_ok=0;
    assert(!device_settings_apply(1UL<<_device_setting_render_height,values));
    assert(render_height==480 && writes==1);
    reset(values);values[_device_setting_render_height]=1080;values[_device_setting_vsync]=0;apply_fail_on=1;
    assert(!device_settings_apply((1UL<<_device_setting_render_height)|(1UL<<_device_setting_vsync),values));
    assert(render_height==480 && saved[6]==1 && writes==2);
    {
        const double invalid[]={-2,1,479,481,900,2880,720.5,INFINITY,NAN};
        for(i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
            reset(values);values[_device_setting_render_height]=invalid[i];
            assert(!device_settings_apply(1UL<<_device_setting_render_height,values) && !writes && render_height==480);
        }
    }
#if CONFIG_FULLSCREEN
    reset(values);render_height=-1;values[_device_setting_render_height]=device_settings_get(_device_setting_render_height);
    assert(values[_device_setting_render_height]==-1);
    assert(device_settings_apply(1UL<<_device_setting_render_height,values) && !writes);
    render_height=99;assert(device_settings_get(_device_setting_render_height)==-1);
    values[_device_setting_render_height]=0;
    assert(device_settings_apply(1UL<<_device_setting_render_height,values) && render_height==0);
    values[_device_setting_render_height]=-1;
    assert(device_settings_apply(1UL<<_device_setting_render_height,values) && render_height==-1);
#else
    reset(values);values[_device_setting_render_height]=-1;
    assert(!device_settings_apply(1UL<<_device_setting_render_height,values) && !writes);
#endif
#else
    reset(values);assert(!HALO_DEVICE_HAS_RENDER_RESOLUTION);
#endif
    return 0;
}
'''


class DesktopVideoResolutionTests(unittest.TestCase):
    def compile_run(self, source, *, defines=(), inputs=(), arguments=(), env=None):
        with tempfile.TemporaryDirectory(prefix="halo-desktop-resolution-") as folder:
            root = Path(folder)
            probe = root / "probe.c"
            probe.write_text(source)
            binary = root / "probe"
            result = subprocess.run(["clang", "-std=gnu11", "-O1", "-g",
                "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-unused-variable", "-Wno-multichar",
                "-fsanitize=address,undefined", *defines, "-I", str(ROOT / "port/linux/game"),
                "-I", str(PORT), "-iquote", str(ROOT / "port/linux/include"), *inputs,
                str(probe), "-o", str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary), *arguments], capture_output=True, text=True, env=env, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_platform_settings_validate_and_rollback_resolution_atomically(self):
        # Reuse only storage/display stubs. Retired menu-repeat preferences in
        # the older full fixture do not participate in these resolution checks.
        source = SETTINGS_HARNESS.split("int main(", 1)[0].replace(
            '"input.fast_menu_repeat", "display.high_res_hud"};',
            '"input.fast_menu_repeat", "display.high_res_hud", "game.show_default_game_types"};') + SETTINGS_MAIN
        for defines in (("-DHALO_LINUX=1",), ("-DHALO_WINDOWS=1",),
                        ("-DHALO_MACOS=1", "-DHALO_ANDROID=1"),
                        ("-DHALO_ANDROID=1",), ("-DHALO_MACOS=1", "-DHALO_IOS=1", "-DHALO_ANDROID=1")):
            with self.subTest(defines=defines), tempfile.TemporaryDirectory(prefix="halo-resolution-c89-") as folder:
                # Compile the production boundary with the game's C89 headers;
                # the storage/display stubs use ordinary host C11 declarations.
                obj = Path(folder) / "settings.o"
                result = subprocess.run(["clang", "-std=gnu89", "-D__STRICT_ANSI__", "-O1",
                    "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", *defines,
                    "-I", str(PORT), "-iquote", str(ROOT / "port/linux/include"), "-c",
                    str(ROOT / "port/linux/game/device_settings.c"), "-o", str(obj)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.compile_run(source, defines=defines, inputs=(str(obj),))

    def test_visibility_counts_remain_logical_above_and_below_480p(self):
        gl = (PORT / "d3d8_gl.c").read_text()
        source = r'''
#include <assert.h>
#include <float.h>
#include <math.h>
typedef unsigned GLuint;
typedef unsigned DWORD;
static struct { float query_area[1]; } device;
''' + function(gl, "static GLuint visibility_unscaled(") + r'''
int main(void) {
    const float legacy_areas[]={1.01f,1.7f,4.0f,20.25f};
    const GLuint legacy_samples[]={0,1,100,16777217,(GLuint)-1};
    unsigned i,j;
    for(i=0;i<sizeof(legacy_areas)/sizeof(legacy_areas[0]);i++) {
        device.query_area[0]=legacy_areas[i];
        for(j=0;j<sizeof(legacy_samples)/sizeof(legacy_samples[0]);j++)
            assert(visibility_unscaled(legacy_samples[j],0)==(GLuint)(legacy_samples[j]/legacy_areas[i]+0.5f));
    }
    device.query_area[0]=0.25f;assert(visibility_unscaled(25,0)==100);
    device.query_area[0]=4;assert(visibility_unscaled(400,0)==100);
    device.query_area[0]=1;assert(visibility_unscaled(100,0)==100);
    device.query_area[0]=0;assert(visibility_unscaled(100,0)==100);
    device.query_area[0]=-1;assert(visibility_unscaled(100,0)==100);
    device.query_area[0]=INFINITY;assert(visibility_unscaled(100,0)==100);
    device.query_area[0]=NAN;assert(visibility_unscaled(100,0)==100);
    device.query_area[0]=FLT_MIN;assert(visibility_unscaled(100,0)==(GLuint)-1);
    assert(visibility_unscaled(0,0)==0);
    device.query_area[0]=0.25f;assert(visibility_unscaled((GLuint)-1,0)==(GLuint)-1);
    return 0;
}
'''
        self.compile_run(source)

    def test_screen_modes_preserve_defaults_and_apply_windowed_native_and_fixed_heights(self):
        gl = (PORT / "d3d8_gl.c").read_text()
        source = r'''
#include <assert.h>
#include <math.h>
#include "desktop_render_scale.h"
#define SCREEN_HEIGHT 480
#define SCREEN_MAXIMUM_WIDTH 1920
static long screen_width,screen_render_maximum=16384,requested=-1;
static float screen_scale[2]={1,1};
static int fullscreen,drawable_width,drawable_height;
static long display_width=1920,display_height=1080;
static int platform_screen_mode(long *width,long *height) { *width=display_width;*height=display_height;return fullscreen; }
static long config_integer(const char *key) { (void)key;return requested; }
static void platform_video_drawable_size(int *width,int *height) { *width=drawable_width;*height=drawable_height; }
''' + function(gl, "static void screen_mode_choose(") + r'''
int main(void) {
    long width;float scale[2];
    screen_mode_choose(&width,scale);assert(width==640 && scale[0]==1 && scale[1]==1);
    fullscreen=1;screen_mode_choose(&width,scale);
    assert(width==852 && fabs(scale[1]-2.25)<0.0001 && (long)(width*scale[0]+0.5)==1920);
    fullscreen=0;requested=1080;screen_mode_choose(&width,scale);
    assert(width==640 && scale[0]==2.25 && scale[1]==2.25);
    requested=0;drawable_width=1280;drawable_height=720;screen_mode_choose(&width,scale);
    assert(width==640 && scale[0]==1.5 && scale[1]==1.5);
    /* Minimize retains the last valid Native size; restore follows drawable pixels. */
    screen_width=width;screen_scale[0]=scale[0];screen_scale[1]=scale[1];
    drawable_width=drawable_height=0;screen_mode_choose(&width,scale);assert(scale[0]==1.5 && scale[1]==1.5);
    drawable_width=2560;drawable_height=1440;screen_mode_choose(&width,scale);assert(scale[0]==3 && scale[1]==3);
    requested=777;screen_mode_choose(&width,scale);assert(scale[0]==1 && scale[1]==1);
    requested=2160;screen_render_maximum=1024;screen_mode_choose(&width,scale);
    assert((long)(width*scale[0]+0.5)<=1024 && (long)(480*scale[1]+0.5)<=1024 && scale[0]==scale[1]);
    fullscreen=1;display_width=7680;display_height=1080;requested=0;drawable_width=7680;drawable_height=1080;
    screen_mode_choose(&width,scale);assert(width==1920 && scale[0]==scale[1]);
    assert((long)(width*scale[0]+0.5)<=1024 && (long)(480*scale[1]+0.5)>0);
    return 0;
}
'''
        self.compile_run(source)

    def test_resize_retires_screen_targets_and_referenced_framebuffers_only(self):
        gl = (PORT / "d3d8_gl.c").read_text()
        source = r'''
#include <assert.h>
#include <stdlib.h>
#define SCREEN_HEIGHT 480
#define RENDER_TARGET_BUCKET_COUNT 256
 typedef unsigned GLuint;
struct xgpu_render_target { unsigned long data,width,height;GLuint texture; };
''' + function(gl, "struct render_target_entry\n") + ";\n" + function(gl, "struct framebuffer_entry\n") + r''';
static struct render_target_entry *render_targets,*render_target_buckets[RENDER_TARGET_BUCKET_COUNT];
static struct framebuffer_entry *framebuffers;
static unsigned textures_deleted,framebuffers_deleted,invalidations;
static void glDeleteTextures(int count,const GLuint *id) { assert(count==1 && (*id==11 || *id==12));textures_deleted++; }
static void glDeleteFramebuffers(int count,const GLuint *id) { assert(count==1 && *id<4);framebuffers_deleted++; }
static void xgpu_gl_state_invalidate(void) { invalidations++; }
''' + function(gl, "static struct render_target_entry **render_target_bucket(") + "\n" + function(gl, "static void screen_render_targets_retire(") + r'''
static void target(unsigned long data,unsigned long width,unsigned long height,GLuint texture) {
    struct render_target_entry *entry=calloc(1,sizeof(*entry));entry->target.data=data;
    entry->target.width=width;entry->target.height=height;entry->target.texture=texture;
    entry->next=render_targets;render_targets=entry;
    entry->next_in_bucket=*render_target_bucket(data);*render_target_bucket(data)=entry;
}
static void framebuffer(GLuint id,GLuint color,GLuint depth) {
    struct framebuffer_entry *entry=calloc(1,sizeof(*entry));entry->framebuffer=id;entry->color=color;entry->depth=depth;
    entry->next=framebuffers;framebuffers=entry;
}
int main(void) {
    target(4096,640,480,11);target(4096,640,480,12);target(4096,256,256,13);target(8192,854,480,14);
    framebuffer(1,11,12);framebuffer(2,11,0);framebuffer(3,13,12);framebuffer(4,13,14);
    screen_render_targets_retire(640);
    assert(textures_deleted==2 && framebuffers_deleted==3 && invalidations==1);
    assert(render_targets->target.texture==14 && render_targets->next->target.texture==13 && !render_targets->next->next);
    assert((*render_target_bucket(4096))->target.texture==13 && !(*render_target_bucket(4096))->next_in_bucket);
    assert(framebuffers->framebuffer==4 && !framebuffers->next);
    screen_render_targets_retire(640);assert(textures_deleted==2 && framebuffers_deleted==3);
    while(render_targets) { struct render_target_entry *next=render_targets->next;free(render_targets);render_targets=next; }
    free(framebuffers);return 0;
}
'''
        self.compile_run(source)

    def test_menu_presets_and_platform_row_counts(self):
        menu = (ROOT / "source/interface/game_settings_menu.inc").read_text()
        definitions = menu[menu.index("#define DEVICE_SETTINGS_ENTRY"):menu.index("#define DEVICE_SETTINGS_STRING_COUNT")]
        build = function(menu, "static boolean device_settings_build(")
        copy = build[build.index("    static char const *const captions"):build.index("    static char const *const heading_names")]
        cycle = function(menu, "static double device_settings_cycle_choice(")
        edit = menu[menu.index("#if HALO_DEVICE_HAS_RENDER_RESOLUTION\n    if (row == _device_setting_render_height)"):]
        edit = edit[:edit.index("    if (row < _device_setting_menu_music")]
        source = r'''
#include <assert.h>
#include <string.h>
#include "device_settings.h"
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
#define NONE -1
''' + definitions + "\n" + copy + "\n" + cycle + r'''
struct draft { double values[NUMBER_OF_DEVICE_SETTINGS]; };
static void edit_height(struct draft *draft,short function) {
    short row=_device_setting_render_height;
''' + edit + r'''    { assert(!"unexpected setting"); }
}
int main(void) {
    struct draft draft={{0}};unsigned i;
    assert(NUMBEROF(row_labels)==NUMBER_OF_DEVICE_SETTINGS && NUMBEROF(help)==NUMBER_OF_DEVICE_SETTINGS);
    assert(strstr(help[_device_setting_render_height],"Accept applies the render height."));
    assert(!strstr(help[_device_setting_render_height],"Relaunch"));
#if defined(HALO_MACOS)
    const short choices[]={0,480,720,1080,1440,2160};
    assert(device_settings_page_counts[_ds_video]==8 && device_settings_page_counts[_ds_timer]==7);
    assert(strstr(captions[_ds_video_help],"Renderer, assets and AA:"));
    assert(!strstr(captions[_ds_video_help],"resolution"));
    assert(strstr(help[_device_setting_renderer],"next launch"));
    assert(strstr(help[_device_setting_asset_quality],"Relaunch"));
    assert(strstr(help[_device_setting_anti_aliasing],"Relaunch"));
#else
    const short choices[]={-1,0,480,720,1080,1440,2160};
    assert(device_settings_page_counts[_ds_video]==7 && device_settings_page_counts[_ds_timer]==5);
#endif
    draft.values[_device_setting_render_height]=choices[0];
    for(i=1;i<=NUMBEROF(choices);i++) { edit_height(&draft,_device_settings_next);assert(draft.values[_device_setting_render_height]==choices[i%NUMBEROF(choices)]); }
    for(i=NUMBEROF(choices)-1;i<NUMBEROF(choices);i--) { edit_height(&draft,_device_settings_previous);assert(draft.values[_device_setting_render_height]==choices[i]); }
    return 0;
}
'''
        for platform in ("HALO_LINUX", "HALO_WINDOWS", "HALO_MACOS"):
            with self.subTest(platform=platform):
                self.compile_run(source, defines=("-D"+platform+"=1",))

    def test_mac_resolution_menu_stages_accepts_cancels_and_keeps_angle_rows_hidden(self):
        menu = (ROOT / "source/interface/game_settings_menu.inc").read_text()
        definitions = menu[menu.index("#define DEVICE_SETTINGS_ENTRY"):menu.index("#define DEVICE_SETTINGS_STRING_COUNT")]
        storage = SETTINGS_HARNESS.split("int main(", 1)[0].replace(
            '"input.fast_menu_repeat", "display.high_res_hud"};',
            '"input.fast_menu_repeat", "display.high_res_hud", "game.show_default_game_types"};')
        source = storage + r'''
typedef int boolean;
#define TRUE 1
#define FALSE 0
#define NONE -1
#define MAXIMUM_NUMBER_OF_LOCAL_PLAYERS 4
#define NUMBEROF(a) (sizeof(a)/sizeof((a)[0]))
#define csmemcpy memcpy
enum { _ui_widget_type_column_list=1, _ui_audio_feedback_flag_failure, _ui_audio_feedback_cursor };
''' + definitions + r'''
struct widget_instance {
    struct widget_instance *parent,*child,*next,*previous,*focused_child;
    long definition_tag_index;
    short type,local_player_index,vertical_offset;
    boolean visible,disabled;
    struct {
        struct { short selected_index,last_list_tab_direction; } list;
        struct { short string_list_index; } text_box;
    } parameters;
};
static struct {
    boolean ready,native_pages;
    unsigned about_page;
    long about_tag,accept_tag,screen_tags[_ds_layout_count][_ds_page_count];
    long row_tags[NUMBER_OF_DEVICE_SETTINGS],heading_tags[_ds_page_count],footer_tags[_ds_page_count];
    struct { short vertical_offset; } column_children[_ds_layout_count][_ds_page_count][DEVICE_SETTINGS_MAX_PAGE_ROWS+1];
} device_settings;
static struct { long spinner_tags[NUMBER_OF_DEVICE_SETTINGS]; } device_settings_native;
''' + function(menu, "static struct device_settings_draft\n") + r''' device_settings_drafts[MAXIMUM_NUMBER_OF_LOCAL_PLAYERS];
static unsigned failures;
static unsigned device_settings_about_page_count(void) { return 1; }
static void device_settings_refresh_about(void) {}
static void ui_play_audio_feedback_sound(short sound) { if(sound==_ui_audio_feedback_flag_failure) failures++; }
static struct widget_instance *widget_instance_find_by_tag_index_recursive(struct widget_instance *root,long tag) {
    struct widget_instance *child,*found;
    if(root->definition_tag_index==tag) return root;
    for(child=root->child;child;child=child->next)
        if((found=widget_instance_find_by_tag_index_recursive(child,tag))) return found;
    return NULL;
}
static short widget_instance_get_child_index_from_parent(struct widget_instance *widget) {
    short index=0;struct widget_instance *child;
    for(child=widget->parent->child;child && child!=widget;child=child->next) index++;
    return index;
}
''' + "\n".join(function(menu, signature) for signature in (
            "static struct device_settings_draft *device_settings_draft_for(",
            "static boolean game_settings_is_native_spinner(",
            "static void device_settings_video_visibility(",
            "static boolean device_settings_video_tab(",
            "static double device_settings_cycle_choice(",
            "static boolean device_settings_is_stick_deadzone(")) + r'''
static void device_settings_render_draft(struct device_settings_draft *draft) { device_settings_video_visibility(draft); }
''' + function(menu, "static boolean game_settings_event(") + r'''
int main(void) {
    double values[NUMBER_OF_DEVICE_SETTINGS];
    struct widget_instance root={0},column={0},rows[DEVICE_SETTINGS_MAX_PAGE_ROWS+1]={{0}},footer={0};
    struct widget_instance *height=NULL,*renderer_row=NULL,*cap=NULL,*aa=NULL;
    struct device_settings_draft *draft=&device_settings_drafts[0];
    const short choices[]={720,1080,1440,2160,0,480};unsigned i;
    reset(values);renderer="metal";
    device_settings.ready=TRUE;device_settings.native_pages=TRUE;device_settings.about_tag=NONE;
    device_settings.accept_tag=200;device_settings.screen_tags[_ds_main][_ds_video]=100;
    device_settings.footer_tags[_ds_video]=300;
    root.definition_tag_index=100;root.child=&column;
    column.parent=&root;column.child=&rows[0];column.type=_ui_widget_type_column_list;column.next=&footer;
    footer.parent=&root;footer.definition_tag_index=300;
    for(i=0;i<NUMBER_OF_DEVICE_SETTINGS;i++) {
        device_settings.row_tags[i]=400+i;
        device_settings_native.spinner_tags[i]=500+i;
    }
    for(i=0;i<=DEVICE_SETTINGS_MAX_PAGE_ROWS;i++) {
        short setting=i<DEVICE_SETTINGS_MAX_PAGE_ROWS ? device_settings_page_rows[_ds_video][i] : NONE;
        rows[i].parent=&column;rows[i].previous=i ? &rows[i-1] : NULL;
        rows[i].next=i<DEVICE_SETTINGS_MAX_PAGE_ROWS ? &rows[i+1] : NULL;
        rows[i].definition_tag_index=setting==NONE ? device_settings.accept_tag : device_settings.row_tags[setting];
        if(setting==_device_setting_render_height) height=&rows[i];
        if(setting==_device_setting_renderer) renderer_row=&rows[i];
        if(setting==_device_setting_frame_limit) cap=&rows[i];
        if(setting==_device_setting_anti_aliasing) aa=&rows[i];
    }
    assert(height && renderer_row && cap && aa);
    assert(game_settings_event(&root,_device_settings_initialize));
    assert(height->visible && !height->disabled && draft->values[_device_setting_render_height]==480);
    for(i=0;i<NUMBEROF(choices);i++) {
        assert(game_settings_event(height,_device_settings_next));
        assert(draft->values[_device_setting_render_height]==choices[i]);
        assert(render_height==480 && !writes && !video_applies);
    }
    assert(game_settings_event(height,_device_settings_next));
    assert(game_settings_event(&root,_device_settings_cancel));
    assert(render_height==480 && !writes);
    assert(game_settings_event(&root,_device_settings_initialize));
    assert(draft->values[_device_setting_render_height]==480);
    assert(game_settings_event(height,_device_settings_next));
    assert(game_settings_event(&root,_device_settings_accept));
    assert(render_height==720 && writes==1 && !video_applies && !audio_applies && !switches);
    assert(draft->original[_device_setting_render_height]==720);
    assert(game_settings_event(&root,_device_settings_accept) && writes==1);
    assert(game_settings_event(height,_device_settings_next));write_ok=0;
    assert(!game_settings_event(&root,_device_settings_accept));
    assert(render_height==720 && writes==2 && failures==1);
    assert(draft->values[_device_setting_render_height]==1080 && draft->original[_device_setting_render_height]==720);
    assert(footer.parameters.text_box.string_list_index==_ds_failure_help);
    write_ok=1;assert(game_settings_event(&root,_device_settings_accept));
    assert(render_height==1080 && writes==3 && !video_applies);
    renderer="angle";column.focused_child=height;
    assert(game_settings_event(&root,_device_settings_initialize));
    assert(!height->visible && height->disabled && !cap->visible && !aa->visible);
    assert(column.focused_child==column.child);
    assert(!game_settings_event(height,_device_settings_next));
    assert(render_height==1080 && draft->values[_device_setting_render_height]==1080 && writes==3);
    assert(game_settings_event(renderer_row,_device_settings_next));
    assert(height->visible && cap->visible && aa->visible && !strcmp(renderer,"angle") && writes==3);
    assert(game_settings_event(height,_device_settings_previous));
    assert(game_settings_event(&root,_device_settings_cancel));
    assert(!strcmp(renderer,"angle") && render_height==1080 && writes==3);
    return 0;
}
'''
        defines = ("-DHALO_MACOS=1", "-DHALO_ANDROID=1")
        with tempfile.TemporaryDirectory(prefix="halo-resolution-menu-") as folder:
            obj = Path(folder) / "settings.o"
            result = subprocess.run(["clang", "-std=gnu89", "-D__STRICT_ANSI__", "-O1",
                "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", *defines,
                "-I", str(PORT), "-iquote", str(ROOT / "port/linux/include"), "-c",
                str(ROOT / "port/linux/game/device_settings.c"), "-o", str(obj)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.compile_run(source, defines=defines, inputs=(str(obj),))

    def test_desktop_gl_present_commits_accepted_resolution_after_swap_and_events(self):
        gl = (PORT / "d3d8_gl.c").read_text()
        source = r'''
#include <assert.h>
#include <string.h>
#define WINAPI
#define CONST const
#define STREAM_BUFFER_SIZE 1024
#define INDEX_BUFFER_SIZE 512
#define GL_DRAW_FRAMEBUFFER 1
#define GL_READ_FRAMEBUFFER 2
#define GL_COLOR_BUFFER_BIT 4
#define GL_LINEAR 8
typedef int RECT,GLint;
typedef unsigned GLuint;
struct render_target_entry { struct { unsigned texture,gl_width,gl_height; } target; };
static struct render_target_entry back_buffer={{1,640,480}};
static struct {
    int gl_ready;
    struct { unsigned long Data; } back_buffer;
    unsigned long frame,stream_offset,index_offset;
} device;
static struct {
    unsigned long presents,draws,immediate_draws,clears,target_changes,skipped_no_program,skipped_no_target,skipped_link;
    unsigned long mirrored_bytes,streamed_bytes;
} stats;
static struct { int statistics; } debug_settings;
static unsigned stage,commits,swaps,events;
static int vertical_blank_lock,vertical_blank_condition,pending_flips,flip_count;
static long config_integer(const char *name) { (void)name;return 0; }
static struct render_target_entry *render_target_get(const void *surface) { (void)surface;return &back_buffer; }
static int trace_frame(void) { return 0; }
static void write_screenshot(const struct render_target_entry *entry) { (void)entry; }
static void platform_video_drawable_size(int *width,int *height) { *width=640;*height=480; }
static GLuint framebuffer_get(GLuint color,GLuint depth) { (void)color;(void)depth;return 1; }
static void glBindFramebuffer(unsigned target,GLuint framebuffer) { (void)target;(void)framebuffer; }
static void glBlitFramebuffer(GLint x0,GLint y0,GLint x1,GLint y1,GLint dx0,GLint dy0,GLint dx1,GLint dy1,unsigned mask,unsigned filter) {
    (void)x0;(void)y0;(void)x1;(void)y1;(void)dx0;(void)dy0;(void)dx1;(void)dy1;(void)mask;(void)filter;
}
static void platform_video_swap(void) { assert(stage==0);stage=1;swaps++; }
static void platform_pump_events(void) { assert(stage==(device.gl_ready ? 1U : 0U));stage=2;events++; }
static long halo_screen_commit(void) { assert(stage==2);stage=3;commits++;return 640; }
static int halo_interpolation_enabled(void) { return 1; }
#define platform_log(...) ((void)0)
#define glDisable(...) ((void)0)
#define glColorMask(...) ((void)0)
#define glClearColor(...) ((void)0)
#define glClear(...) ((void)0)
#define gl_check_errors(...) ((void)0)
#define xgpu_gl_state_invalidate() ((void)0)
#define xgpu_texture_cache_begin_frame() ((void)0)
#define pthread_mutex_lock(...) assert(stage==(device.gl_ready ? 3U : 2U))
#define pthread_mutex_unlock(...) ((void)0)
#define pthread_cond_wait(...) ((void)0)
''' + function(gl, "void WINAPI D3DDevice_Present(") + r'''
int main(void) {
    device.gl_ready=1;
    D3DDevice_Present(NULL,NULL,NULL,NULL);
    assert(commits==1 && swaps==1 && events==1 && device.frame==1 && flip_count==1);
    stage=0;D3DDevice_Present(NULL,NULL,NULL,NULL);
    assert(commits==2 && swaps==2 && events==2 && device.frame==2);
    stage=0;device.gl_ready=0;D3DDevice_Present(NULL,NULL,NULL,NULL);
    assert(commits==2 && swaps==2 && events==3 && device.frame==3);
    return 0;
}
'''
        self.compile_run(source, defines=("-DHALO_LINUX=1",))

    def test_config_default_and_resolution_save_reload(self):
        if not (SDL / "include/SDL3/SDL.h").exists():
            self.skipTest("SDL3 headers required")
        source = CONFIG_HARNESS.split("int main(", 1)[0] + r'''
int main(int argc,char **argv) {
    long expected=atol(argv[1]);const char *key="display.render_height";double height=1080;
    (void)argc;assert(config_integer(key)==expected);
    assert(config_write_numbers(&key,&height,1));assert(config_integer(key)==1080);
    return 0;
}
'''
        for defines,expected in (((),"-1"), (("-DHALO_MACOS=1","-DHALO_ANDROID=1"),"480")):
            with self.subTest(defines=defines),tempfile.TemporaryDirectory(prefix="halo-resolution-config-") as folder:
                prefix=Path(folder)/"prefix.h";prefix.write_text(PREFIX)
                env={key:value for key,value in os.environ.items() if not key.startswith("HALO_")}
                env.update(HALO_SAVE_ROOT=folder,HALO_DATA_ROOT=folder)
                inputs=("-pthread","-include",str(prefix),"-I",str(SDL/"include"),"-I",str(ROOT/"port/third_party/tomlc17"),
                        str(PORT/"port_config.c"),str(ROOT/"port/third_party/tomlc17/tomlc17.c"))
                self.compile_run(source,defines=defines,inputs=inputs,arguments=(expected,),env=env)
                self.compile_run(source,defines=defines,inputs=inputs,arguments=("1080",),env=env)


if __name__ == "__main__":
    unittest.main()
