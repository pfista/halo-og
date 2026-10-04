"""Exercise production disc discovery/import against synthetic Xbox images.

No original game data, user setting, desktop window or network is involved.
The actual XDVDFS reader, staging publication, data-root selection and SDL
first-run orchestration are compiled; only user dialogs are stubbed.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.test_save_migration import function

ROOT = Path(__file__).resolve().parents[1]


def map_header(version=5, build=b"01.10.12.2276"):
    data = bytearray(2048)
    struct.pack_into("<4sII", data, 0, b"daeh", version, len(data))
    data[64:64 + len(build)] = build
    data[-4:] = b"toof"
    return bytes(data)


def disc_image(*, root_name=b"maps", ui_name=b"ui.map", ui_version=5, second_name=b"a10.map"):
    data = bytearray(44 * 2048)
    magic = b"MICROSOFT*XBOX*MEDIA"
    data[32 * 2048:32 * 2048 + 20] = magic
    data[33 * 2048 - 20:33 * 2048] = magic
    struct.pack_into("<II", data, 32 * 2048 + 20, 40, 32)
    root = struct.pack("<HHIIBB", 0, 0, 41, 80, 0x10, len(root_name)) + root_name
    data[40 * 2048:40 * 2048 + len(root)] = root
    for offset, right, sector, name in ((0, 10, 42, ui_name), (40, 0, 43, second_name)):
        entry = struct.pack("<HHIIBB", 0, right, sector, 2048, 0, len(name)) + name
        data[41 * 2048 + offset:41 * 2048 + offset + len(entry)] = entry
    data[42 * 2048:43 * 2048] = map_header(ui_version)
    data[43 * 2048:44 * 2048] = bytes(range(256)) * 8
    return bytes(data)


HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#ifndef _WIN32
#include <unistd.h>
#include <strings.h>
#define SDL_strcasecmp strcasecmp
#else
#define SDL_strcasecmp _stricmp
#define readlink fixture_readlink
static int fixture_readlink(const char *, char *, size_t);
#endif
#include "posix.h"
#include "xiso.h"
typedef int BOOL;
#define TRUE 1
#define FALSE 0
#define MAX_PATH 260
#define SDL_INIT_VIDEO 1
#define SDL_MESSAGEBOX_INFORMATION 1
#define SDL_MESSAGEBOX_ERROR 2
#define SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT 1
#define SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT 2
typedef struct { int flags, buttonid; const char *text; } SDL_MessageBoxButtonData;
typedef struct { int flags; void *window; const char *title, *message; int count;
                 const SDL_MessageBoxButtonData *buttons; void *colors; } SDL_MessageBoxData;
static const char *configured_root = "", *executable_path;
static int picker_calls, extraction_calls, questions;
static const char *config_string(const char *key) { (void)key; return configured_root; }
static int config_boolean(const char *key) { (void)key; return 0; }
static double config_real(const char *key) { (void)key; return 0; }
static int SDL_Init(int flags) { (void)flags; return 1; }
static int SDL_ShowMessageBox(const SDL_MessageBoxData *question, int *answer) {
    questions++; fprintf(stderr,"question: %s\n",question->message); *answer=0; return 1;
}
static void SDL_ShowSimpleMessageBox(int type, const char *title, const char *message, void *window) {
    (void)type; (void)title; (void)window; fprintf(stderr,"message: %s\n",message);
}
static void platform_log(const char *format, ...) {
    va_list arguments; va_start(arguments,format); vfprintf(stderr,format,arguments); va_end(arguments); fputc('\n',stderr);
}
static BOOL data_extract(const char *image, const char *destination, char *error, int size) {
    extraction_calls++; return xiso_extract_maps(image,destination,NULL,NULL,error,size);
}
static BOOL data_choose_image(char *path, int size) { (void)path; (void)size; picker_calls++; return FALSE; }
/* DISCOVERY_FUNCTIONS */
#ifndef _WIN32
#define readlink fixture_readlink
static ssize_t fixture_readlink(const char *path, char *buffer, size_t size) {
#else
static int fixture_readlink(const char *path, char *buffer, size_t size) {
#endif
    size_t length=strlen(executable_path); (void)path;
    if (length>size) return -1; memcpy(buffer,executable_path,length); return (int)length;
}
/* ROOT_FUNCTIONS */
int main(int count, char **arguments) {
    char path[1024], error[512]=""; int result;
    if(count<3) return 2;
    if(!strcmp(arguments[1],"probe")) {
        result=xiso_probe_maps(arguments[2],error,sizeof(error)); printf("%d\n%s\n",result,error); return 0;
    }
    if(!strcmp(arguments[1],"discover")) {
        result=data_find_adjacent_image(arguments[2],path,sizeof(path),error,sizeof(error));
        printf("%d\n%s\n%s\n",result,path,error); return 0;
    }
    if(!strcmp(arguments[1],"extract") && count==4) {
        result=xiso_extract_maps(arguments[2],arguments[3],NULL,NULL,error,sizeof(error));
        printf("%d\n%s\n",result,error); return 0;
    }
    if(!strcmp(arguments[1],"has-maps")) { printf("%d\n",has_maps(arguments[2])); return 0; }
    if(!strcmp(arguments[1],"root")) {
        executable_path=arguments[2]; if(count>3) configured_root=arguments[3];
        puts(platform_data_root()); fprintf(stderr,"extract=%d picker=%d questions=%d\n",extraction_calls,picker_calls,questions); return 0;
    }
    return 2;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang is required for production C fixtures")
class DesktopFirstRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build.cleanup)
        directory = Path(cls.build.name).resolve()
        sdl = (ROOT / "port/linux/src/sdl_platform.c").read_text()
        files = (ROOT / "port/linux/src/xbox_files.c").read_text()
        discovery = "\n".join(function(sdl, name) for name in (
            "static int data_find_adjacent_image(", "BOOL platform_offer_game_data("))
        selection = "\n".join(function(files, name) for name in (
            "static BOOL directory_exists(", "static BOOL has_maps(",
            "static void trim_separators(", "const char *platform_data_root("))
        harness = directory / "fixture.c"
        harness.write_text(HARNESS.replace("/* DISCOVERY_FUNCTIONS */", discovery).replace("/* ROOT_FUNCTIONS */", selection))
        cls.binary = directory / ("first-run.exe" if sys.platform == "win32" else "first-run")
        command = ["clang", "-std=gnu11", "-Wall", "-Wextra", "-DHALO_MACOS",
                   "-I", str(ROOT / "port/linux/src"), str(harness), str(ROOT / "port/linux/src/xiso.c")]
        if sys.platform == "win32":
            command += ["-D_CRT_SECURE_NO_WARNINGS", "-D_CRT_NONSTDC_NO_DEPRECATE", "-DWIN32_LEAN_AND_MEAN",
                        "-I", str(ROOT / "port/windows/include/posix"), str(ROOT / "port/windows/src/win32_files.c")]
        elif sys.platform == "darwin":
            command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", str(ROOT / "port/macos/host/posix_files.c")]
        else:
            command += ["-D_GNU_SOURCE", "-D_FILE_OFFSET_BITS=64", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                        str(ROOT / "port/linux/src/posix_files.c")]
        subprocess.run([*command, "-o", str(cls.binary)], check=True, capture_output=True, text=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.app = self.folder / "app"
        self.app.mkdir()
        self.image = self.app / "Halo.iso"

    def run_fixture(self, command, *arguments, cwd=None):
        return subprocess.run([str(self.binary), command, *map(str, arguments)],
                              cwd=cwd or self.folder, text=True, capture_output=True, check=True, timeout=15)

    def write_image(self, name=None, **options):
        path = self.app / name if name else self.image
        path.write_bytes(disc_image(**options))
        return path

    def make_data(self, folder):
        (folder / "Maps").mkdir(parents=True)
        (folder / "Maps/UI.MAP").write_bytes(map_header())

    def test_probe_validates_contents_and_is_read_only(self):
        image = self.write_image("renamed.data")
        before = image.read_bytes()
        self.assertTrue(self.run_fixture("probe", image).stdout.startswith("1\n"))
        self.assertEqual(image.read_bytes(), before)
        self.assertEqual(list(self.app.iterdir()), [image])

    def test_extension_does_not_make_pc_iso_an_xiso(self):
        self.image.write_bytes(b"fake ISO")
        self.assertIn("not an Xbox disc image", self.run_fixture("probe", self.image).stdout)

    def test_probe_accepts_pal_and_rejects_unsupported_builds(self):
        for build, expected in ((b"01.01.14.2342", "1"), (b"unknown", "0")):
            with self.subTest(build=build):
                image = bytearray(disc_image())
                image[42 * 2048:43 * 2048] = map_header(build=build)
                self.image.write_bytes(image)
                self.assertEqual(self.run_fixture("probe", self.image).stdout.splitlines()[0], expected)

    def test_rejects_missing_maps_missing_ui_and_pc_cache(self):
        for options, reason in (({"root_name": b"other"}, "no maps folder"),
                                ({"ui_name": b"other.map"}, "no ui.map"),
                                ({"ui_version": 7}, "original Xbox Halo cache")):
            with self.subTest(options=options):
                self.write_image(**options)
                self.assertIn(reason, self.run_fixture("probe", self.image).stdout)

    def test_discovers_uppercase_extension_and_ignores_invalid_images(self):
        image = self.write_image("Halo.XISO")
        (self.app / "pc.iso").write_bytes(b"PC ISO")
        result = self.run_fixture("discover", self.app).stdout.splitlines()
        self.assertEqual(result[:2], ["1", str(image)])

    def test_multiple_supported_images_require_picker(self):
        self.write_image()
        self.write_image("second.iso")
        result = self.run_fixture("discover", self.app).stdout.splitlines()
        self.assertEqual(result[:2], ["-1", ""])
        self.assertIn("More than one", result[2])
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertIn("More than one", result.stderr)
        self.assertFalse((self.app / "maps").exists())

    def test_invalid_adjacent_image_explains_picker_fallback(self):
        self.image.write_bytes(b"not Xbox")
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertIn("do not contain a readable Halo Xbox maps folder", result.stderr)
        self.assertFalse((self.app / "maps").exists())

    def test_no_adjacent_image_preserves_picker_fallback(self):
        result = self.run_fixture("discover", self.app)
        self.assertEqual(result.stdout.splitlines()[:2], ["0", ""])
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertIn("game data (its maps folder) was not found", result.stderr)
        self.assertFalse((self.app / "maps").exists())

    def test_first_run_imports_adjacent_image_without_dialog_or_picker(self):
        self.write_image()
        before = self.image.read_bytes()
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertEqual(result.stdout.strip(), str(self.app))
        self.assertIn("extract=1 picker=0 questions=0", result.stderr)
        self.assertEqual((self.app / "maps/ui.map").read_bytes(), map_header())
        self.assertEqual((self.app / "maps/a10.map").read_bytes(), bytes(range(256)) * 8)
        self.assertEqual(self.image.read_bytes(), before)

    def test_stale_partial_files_are_preserved(self):
        self.write_image()
        partial = self.app / "maps.partial"
        partial.mkdir()
        (partial / "ui.map").write_bytes(b"keep this")
        result = self.run_fixture("extract", self.image, self.app)
        self.assertTrue(result.stdout.startswith("1\n"))
        self.assertEqual((partial / "ui.map").read_bytes(), b"keep this")
        self.assertTrue((self.app / "maps/ui.map").exists())

    def test_existing_destination_files_are_never_replaced(self):
        self.write_image()
        (self.app / "maps").mkdir()
        original = self.app / "maps/ui.map"
        original.write_bytes(b"existing user's map")
        result = self.run_fixture("extract", self.image, self.app)
        self.assertIn("destination already contains", result.stdout)
        self.assertEqual(original.read_bytes(), b"existing user's map")
        self.assertFalse((self.app / "maps.partial").exists())

    def test_incomplete_import_is_never_published_and_retry_preserves_it(self):
        self.write_image()
        self.image.write_bytes(self.image.read_bytes()[:-512])
        result = self.run_fixture("extract", self.image, self.app)
        self.assertTrue(result.stdout.startswith("0\n"))
        self.assertFalse((self.app / "maps").exists())
        partial = self.app / "maps.partial/ui.map"
        before = partial.read_bytes()
        self.write_image()
        self.assertTrue(self.run_fixture("extract", self.image, self.app).stdout.startswith("1\n"))
        self.assertEqual(partial.read_bytes(), before)

    def test_directory_traversal_entry_does_not_escape_staging(self):
        self.write_image(second_name=b"../escaped.map")
        self.assertTrue(self.run_fixture("extract", self.image, self.app).stdout.startswith("1\n"))
        self.assertFalse((self.app / "escaped.map").exists())

    def test_original_data_must_contain_ui_and_maps_must_be_directory(self):
        (self.app / "maps").mkdir()
        (self.app / "maps/downrush.map").write_bytes(b"custom")
        self.assertEqual(self.run_fixture("has-maps", self.app).stdout.strip(), "0")
        (self.app / "maps/UI.MAP").write_bytes(map_header())
        self.assertEqual(self.run_fixture("has-maps", self.app).stdout.strip(), "1")

    def test_ui_directory_or_maps_file_is_not_original_data(self):
        (self.app / "maps").write_bytes(b"not a directory")
        self.assertEqual(self.run_fixture("has-maps", self.app).stdout.strip(), "0")
        (self.app / "maps").unlink()
        (self.app / "maps/ui.map").mkdir(parents=True)
        self.assertEqual(self.run_fixture("has-maps", self.app).stdout.strip(), "0")

    def test_custom_only_folder_is_preserved_with_actionable_message(self):
        self.write_image()
        (self.app / "maps").mkdir()
        custom = self.app / "maps/downrush.map"
        custom.write_bytes(b"custom")
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertIn("does not contain the original game's ui.map", result.stderr)
        self.assertIn("Your files were preserved", result.stderr)
        self.assertEqual(custom.read_bytes(), b"custom")
        self.assertFalse((self.app / "maps/ui.map").exists())

    def test_configured_custom_only_folder_does_not_bypass_import(self):
        configured = self.folder / "configured"
        (configured / "maps").mkdir(parents=True)
        custom = configured / "maps/custom.map"
        custom.write_bytes(b"preserve")
        result = self.run_fixture("root", self.app / "halo.exe", configured)
        self.assertIn("does not contain the original game's ui.map", result.stderr)
        self.assertEqual(custom.read_bytes(), b"preserve")

    def test_existing_data_and_config_priority_prevent_import(self):
        self.write_image()
        configured = self.folder / "configured"
        self.make_data(configured)
        result = self.run_fixture("root", self.app / "halo.exe", configured)
        self.assertEqual(result.stdout.strip(), str(configured))
        self.assertIn("extract=0", result.stderr)
        self.make_data(self.folder)
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertEqual(result.stdout.strip(), ".")
        self.assertIn("extract=0", result.stderr)
        self.assertFalse((self.app / "maps").exists())

    def test_existing_executable_and_assets_data_prevent_import(self):
        self.write_image()
        self.make_data(self.app)
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertEqual(result.stdout.strip(), str(self.app))
        self.assertIn("extract=0", result.stderr)
        shutil.rmtree(self.app / "Maps")
        self.make_data(self.folder / "assets")
        result = self.run_fixture("root", self.app / "halo.exe")
        self.assertEqual(result.stdout.strip(), "assets")
        self.assertIn("extract=0", result.stderr)


if __name__ == "__main__":
    unittest.main()
