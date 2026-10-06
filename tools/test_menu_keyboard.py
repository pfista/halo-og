"""Exercise ordered native menu keys through the real SDL event pump."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.test_input_bindings import PREFIX, ROOT, PORT, SDL
from tools.test_macos_input import HARNESS
from tools.test_controller_settings import compile_and_run
from tools.test_performance_variants import block


MAIN = r'''
int main(void) {
    struct halo_menu_keyboard_event edge;
    struct platform_input_state gameplay;
    SDL_Event event = {0};
    unsigned i;

    input_state.focused = TRUE;
    platform_ui_pointer_set_active(TRUE);
    key(SDL_SCANCODE_LEFT, 1, 0);
    key(SDL_SCANCODE_LEFT, 0, 0);
    key(SDL_SCANCODE_LEFT, 1, 0);
    key(SDL_SCANCODE_LEFT, 0, 0);
    assert(!halo_menu_keyboard_held());
    for (i = 0; i < 4; i++) {
        assert(halo_menu_keyboard_next(&edge));
        assert(edge.pressed == (i % 2 ? 0 : HALO_MENU_DIRECTION_LEFT));
        assert(edge.released == (i % 2 ? HALO_MENU_DIRECTION_LEFT : 0));
        assert(edge.held == edge.pressed);
    }
    assert(!halo_menu_keyboard_next(&edge));
    /* Original/gameplay's one-shot latch remains independent and unchanged. */
    gameplay = snapshot(); assert(gameplay.keys[SDL_SCANCODE_LEFT]);
    gameplay = snapshot(); assert(!gameplay.keys[SDL_SCANCODE_LEFT]);

    key(SDL_SCANCODE_LEFT, 1, 0);
    assert(halo_menu_keyboard_next(&edge) && edge.pressed == HALO_MENU_DIRECTION_LEFT);
    key(SDL_SCANCODE_LEFT, 1, 1);
    key(SDL_SCANCODE_LEFT, 1, 0); /* No intervening release: not a fresh press. */
    assert(!halo_menu_keyboard_next(&edge));
    assert(halo_menu_keyboard_held() == HALO_MENU_DIRECTION_LEFT);
    halo_menu_keyboard_clear();
    assert(halo_menu_keyboard_held() == HALO_MENU_DIRECTION_LEFT);
    key(SDL_SCANCODE_LEFT, 0, 0);
    assert(halo_menu_keyboard_next(&edge) && edge.released == HALO_MENU_DIRECTION_LEFT && !edge.held);

    /* Two keys mapped to one direction remain two physical presses. */
    key(SDL_SCANCODE_LEFT, 1, 0); key(SDL_SCANCODE_HOME, 1, 0);
    key(SDL_SCANCODE_LEFT, 0, 0);
    assert(halo_menu_keyboard_next(&edge) && edge.pressed == HALO_MENU_DIRECTION_LEFT);
    assert(halo_menu_keyboard_next(&edge) && edge.pressed == HALO_MENU_DIRECTION_LEFT);
    assert(halo_menu_keyboard_next(&edge) && edge.released == HALO_MENU_DIRECTION_LEFT &&
        edge.held == HALO_MENU_DIRECTION_LEFT);
    key(SDL_SCANCODE_HOME, 0, 0); halo_menu_keyboard_clear();

    key(SDL_SCANCODE_W, 1, 0);
    assert(halo_menu_keyboard_next(&edge));
    assert(edge.pressed == (HALO_MENU_DIRECTION_UP << HALO_MENU_KEYBOARD_MOVE_SHIFT));
    assert(edge.held == edge.pressed);
    key(SDL_SCANCODE_S, 1, 0);
    assert(halo_menu_keyboard_next(&edge) &&
        edge.pressed == (HALO_MENU_DIRECTION_DOWN << HALO_MENU_KEYBOARD_MOVE_SHIFT) && !edge.held);
    key(SDL_SCANCODE_S, 0, 0);
    assert(halo_menu_keyboard_next(&edge) &&
        edge.held == (HALO_MENU_DIRECTION_UP << HALO_MENU_KEYBOARD_MOVE_SHIFT));
    key(SDL_SCANCODE_W, 0, 0); halo_menu_keyboard_clear();

    /* Explicit hotkeys win even when also configured as menu directions. */
    key(SDL_SCANCODE_F2, 1, 0); key(SDL_SCANCODE_F2, 0, 0);
    key(SDL_SCANCODE_F12, 1, 0); key(SDL_SCANCODE_F12, 0, 0);
    key(SDL_SCANCODE_F11, 1, 0); key(SDL_SCANCODE_F11, 0, 0);
    key(SDL_SCANCODE_ESCAPE, 1, 0); key(SDL_SCANCODE_ESCAPE, 0, 0);
    assert(!halo_menu_keyboard_next(&edge) && !halo_menu_keyboard_held());

    key(SDL_SCANCODE_LEFT, 1, 0); console_open = 1;
    assert(!halo_menu_keyboard_next(&edge) && !halo_menu_keyboard_held());
    key(SDL_SCANCODE_LEFT, 0, 0); console_open = 0;
    assert(!halo_menu_keyboard_held());
    key(SDL_SCANCODE_LEFT, 1, 0);
    event.type = SDL_EVENT_WINDOW_FOCUS_LOST; pump(event);
    assert(!halo_menu_keyboard_next(&edge) && !halo_menu_keyboard_held());
    key(SDL_SCANCODE_LEFT, 1, 0);
    assert(!halo_menu_keyboard_next(&edge));
    event.type = SDL_EVENT_WINDOW_FOCUS_GAINED; pump(event);
    assert(!halo_menu_keyboard_held());

    platform_ui_pointer_set_active(FALSE);
    key(SDL_SCANCODE_LEFT, 1, 0);
    assert(!halo_menu_keyboard_next(&edge) && !halo_menu_keyboard_held());
    platform_ui_pointer_set_active(TRUE);
    for (i = 0; i < 200; i++) {
        key(SDL_SCANCODE_LEFT, 1, 0); key(SDL_SCANCODE_LEFT, 0, 0);
    }
    for (i = 0; i < 400; i++) {
        assert(halo_menu_keyboard_next(&edge));
        assert(edge.pressed == (i % 2 ? 0 : HALO_MENU_DIRECTION_LEFT));
        assert(edge.released == (i % 2 ? HALO_MENU_DIRECTION_LEFT : 0));
    }
    assert(!halo_menu_keyboard_next(&edge) && !halo_menu_keyboard_held());
    puts("Native menu keyboard transitions passed");
    return 0;
}
'''


class MenuKeyboardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("clang") and (SDL / "include/SDL3/SDL.h").exists(),
                         "clang and SDL3 headers required")
    def test_nonkeyboard_binding_sources_remain_in_navigation_snapshot(self):
        source = (PORT / "xinput_sdl.c").read_text()
        mapping = "\n".join(block(source, signature) for signature in (
            "static BYTE analog(", "static void keyboard_gamepad(", "static void keyboard_navigation_gamepad("))
        constants = "\n".join(line for line in (ROOT / "port/include/xdk/xdk_xbox.h").read_text().splitlines()
                              if line.startswith("#define XINPUT_GAMEPAD_"))
        fixture = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <SDL3/SDL.h>
#include "sdl_platform.h"
#include "input_bindings.h"
static Uint64 wheel_press_until_ms;
Uint64 SDL_GetTicks(void) { return 100; }
void platform_log(const char *format, ...) { (void)format; }
const char *config_string(const char *name) {
    if (!strcmp(name, "bindings.move_right")) return "D, MouseX1";
    if (!strcmp(name, "bindings.move_forward")) return "W, MouseRight";
    if (!strcmp(name, "bindings.dpad_left")) return "Left, MouseX2, Wheel";
#define BINDING(action, mac, other, comment) if (!strcmp(name, "bindings." #action)) return mac;
#include "input_bindings.def"
#undef BINDING
    return "";
}
/* CONSTANTS */
/* PRODUCTION */
int main(void) {
    struct platform_input_state input = {0};
    XINPUT_GAMEPAD gameplay = {0}, navigation = {0};
    input.keys[SDL_SCANCODE_D] = input.keys[SDL_SCANCODE_W] = input.keys[SDL_SCANCODE_LEFT] = 1;
    keyboard_gamepad(&input, &gameplay);
    keyboard_navigation_gamepad(&input, &navigation);
    assert(gameplay.sThumbLX > 0 && gameplay.sThumbLY > 0 &&
        (gameplay.wButtons & XINPUT_GAMEPAD_DPAD_LEFT));
    assert(!navigation.sThumbLX && !navigation.sThumbLY && !navigation.wButtons);
    input.mouse_buttons[SDL_BUTTON_X1] = input.mouse_buttons[SDL_BUTTON_RIGHT] = 1;
    wheel_press_until_ms = 200;
    keyboard_navigation_gamepad(&input, &navigation);
    assert(navigation.sThumbLX == gameplay.sThumbLX && navigation.sThumbLY == gameplay.sThumbLY);
    assert(navigation.wButtons == XINPUT_GAMEPAD_DPAD_LEFT);
    navigation = (XINPUT_GAMEPAD){0}; input.mouse_released = TRUE;
    keyboard_navigation_gamepad(&input, &navigation);
    assert(!navigation.sThumbLX && !navigation.sThumbLY && !navigation.wButtons);
    input.ui_pointer = TRUE; keyboard_navigation_gamepad(&input, &navigation);
    assert(!navigation.sThumbLX && !navigation.sThumbLY && !navigation.wButtons);
    return 0;
}
'''
        binding_code = (PORT / "input_bindings.c").read_text()
        compile_and_run(PREFIX + fixture.replace("/* CONSTANTS */", constants).replace(
            "/* PRODUCTION */", binding_code + mapping), flags=("-DHALO_MACOS=1",), sdl=True)

    @unittest.skipUnless(shutil.which("clang") and (SDL / "include/SDL3/SDL.h").exists(),
                         "clang and SDL3 headers required")
    def test_real_key_edges_and_gates_preserve_gameplay_latch(self):
        source = (PORT / "sdl_platform.c").read_text()
        foreground = "static void platform_directory_foreground_update(" + source.split(
            "static void platform_directory_foreground_update(", 1)[1].split(
            "static struct platform_input_state", 1)[0]
        tracking = "/* Menu key edges" + source.split("/* Menu key edges", 1)[1].split(
            "/* debug keyboard queue */", 1)[0]
        controls = "void platform_mouse_capture(" + source.split("void platform_mouse_capture(", 1)[1].split(
            "/* ---------- keyboard translation */", 1)[0]
        translation = source.split("/* ---------- keyboard translation */", 1)[1].split(
            "/* ---------- internet play", 1)[0]
        events = "\n".join(block(source, signature) for signature in (
            "void platform_pump_events(", "void platform_ui_pointer_set_active(",
            "void platform_input_read("))
        harness = HARNESS.split("int main(void)", 1)[0] + MAIN
        harness = harness.replace('const char *config_string(const char *name) {',
            'const char *config_string(const char *name) {\n'
            '    if (!strcmp(name, "bindings.dpad_left")) return "Left,Home,F2,F12,F11,Escape";')
        # Keep desktop hotkeys enabled; all host work is replaced with authored stubs.
        harness = harness.replace("/* PRODUCTION_CODE */", r'''
static void updater_poll(SDL_Window *window) { (void)window; }
bool SDL_SetWindowFullscreen(SDL_Window *window, bool fullscreen) { (void)window; (void)fullscreen; return true; }
''' + foreground + tracking + controls + translation + events)
        with tempfile.TemporaryDirectory(prefix="halo-menu-keyboard-") as temporary:
            directory = Path(temporary)
            (directory / "prefix.h").write_text(PREFIX)
            (directory / "probe.c").write_text(harness)
            executable = directory / "probe"
            compiled = subprocess.run([
                "clang", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                "-Wno-unused-function", "-fsanitize=undefined", "-DHALO_MACOS=1",
                "-include", str(directory / "prefix.h"), f"-I{PORT}",
                "-iquote", str(ROOT / "port/linux/include"), f"-I{SDL / 'include'}",
                str(directory / "probe.c"), str(PORT / "input_bindings.c"), "-o", str(executable)
            ], text=True, capture_output=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            tested = subprocess.run([executable], text=True, capture_output=True, timeout=5)
            self.assertEqual(tested.returncode, 0, tested.stderr)
            self.assertIn("Native menu keyboard transitions passed", tested.stdout)


if __name__ == "__main__":
    unittest.main()
