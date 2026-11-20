"""An in-place update leaves a game folder holding one whole version, never a mix.

The production installer (port/linux/src/update_install.c) runs against real
files here. Only its system side is authored: the download copies a fixture
zip, and one named file can be made impossible to replace.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]

SDL = r'''
#ifndef TEST_SDL_H
#define TEST_SDL_H
#include <stdbool.h>
#include <stddef.h>
typedef long long Sint64;
typedef struct SDL_IOStream SDL_IOStream;
typedef struct SDL_Window SDL_Window;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct SDL_Thread SDL_Thread;
typedef struct SDL_Mutex SDL_Mutex;
typedef struct SDL_FRect { float x, y, w, h; } SDL_FRect;
typedef struct SDL_Event { int type; } SDL_Event;
#define SDLCALL
#define SDL_IO_SEEK_SET 0
#define SDL_IO_SEEK_CUR 1
#define SDL_SOFTWARE_RENDERER "software"
SDL_IOStream *SDL_IOFromFile(const char *, const char *);
size_t SDL_ReadIO(SDL_IOStream *, void *, size_t);
size_t SDL_WriteIO(SDL_IOStream *, const void *, size_t);
Sint64 SDL_SeekIO(SDL_IOStream *, Sint64, int);
Sint64 SDL_TellIO(SDL_IOStream *);
Sint64 SDL_GetIOSize(SDL_IOStream *);
bool SDL_CloseIO(SDL_IOStream *);
bool SDL_GetPathInfo(const char *, void *);
void *SDL_LoadFile(const char *, size_t *);
void SDL_free(void *);
const char *SDL_GetError(void);
SDL_Mutex *SDL_CreateMutex(void);
void SDL_LockMutex(SDL_Mutex *);
void SDL_UnlockMutex(SDL_Mutex *);
void SDL_DestroyMutex(SDL_Mutex *);
SDL_Thread *SDL_CreateThread(int (*)(void *), const char *, void *);
void SDL_WaitThread(SDL_Thread *, int *);
SDL_Window *SDL_CreateWindow(const char *, int, int, unsigned);
SDL_Renderer *SDL_CreateRenderer(SDL_Window *, const char *);
void SDL_DestroyRenderer(SDL_Renderer *);
void SDL_DestroyWindow(SDL_Window *);
bool SDL_PollEvent(SDL_Event *);
bool SDL_SetRenderDrawColor(SDL_Renderer *, unsigned char, unsigned char, unsigned char, unsigned char);
bool SDL_RenderClear(SDL_Renderer *);
bool SDL_SetRenderScale(SDL_Renderer *, float, float);
bool SDL_RenderDebugText(SDL_Renderer *, float, float, const char *);
bool SDL_RenderFillRect(SDL_Renderer *, const SDL_FRect *);
bool SDL_RenderPresent(SDL_Renderer *);
void SDL_Delay(unsigned);
#endif
'''

HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "update_install.c"

static const char *game_folder, *fixture_zip, *unreplaceable = "";
static int launches;

/* SDL's file streams over stdio */
SDL_IOStream *SDL_IOFromFile(const char *path, const char *mode) { return (SDL_IOStream *)fopen(path, mode); }
size_t SDL_ReadIO(SDL_IOStream *file, void *data, size_t size) { return fread(data, 1, size, (FILE *)file); }
size_t SDL_WriteIO(SDL_IOStream *file, const void *data, size_t size) { return fwrite(data, 1, size, (FILE *)file); }
Sint64 SDL_SeekIO(SDL_IOStream *file, Sint64 offset, int whence) {
    return fseek((FILE *)file, (long)offset, whence == SDL_IO_SEEK_SET ? SEEK_SET : SEEK_CUR) ? -1 : ftell((FILE *)file);
}
Sint64 SDL_TellIO(SDL_IOStream *file) { return ftell((FILE *)file); }
Sint64 SDL_GetIOSize(SDL_IOStream *file) {
    long at = ftell((FILE *)file), size;
    fseek((FILE *)file, 0, SEEK_END); size = ftell((FILE *)file); fseek((FILE *)file, at, SEEK_SET); return size;
}
bool SDL_CloseIO(SDL_IOStream *file) { return fclose((FILE *)file) == 0; }
bool SDL_GetPathInfo(const char *path, void *info) { struct stat found; (void)info; return stat(path, &found) == 0; }
void *SDL_LoadFile(const char *path, size_t *size) {
    FILE *file = fopen(path, "rb"); char *data; long length;
    if (!file) return NULL;
    fseek(file, 0, SEEK_END); length = ftell(file); rewind(file);
    data = malloc((size_t)length + 1); assert(data && fread(data, 1, (size_t)length, file) == (size_t)length);
    data[length] = 0; fclose(file); *size = (size_t)length; return data;
}
void SDL_free(void *data) { free(data); }
const char *SDL_GetError(void) { return "fixture"; }
/* The download runs on the calling thread and no window is opened. */
SDL_Mutex *SDL_CreateMutex(void) { return (SDL_Mutex *)&launches; }
void SDL_LockMutex(SDL_Mutex *mutex) { (void)mutex; }
void SDL_UnlockMutex(SDL_Mutex *mutex) { (void)mutex; }
void SDL_DestroyMutex(SDL_Mutex *mutex) { (void)mutex; }
SDL_Thread *SDL_CreateThread(int (*run)(void *), const char *name, void *context) { (void)name; run(context); return (SDL_Thread *)&launches; }
void SDL_WaitThread(SDL_Thread *thread, int *status) { (void)thread; (void)status; }
SDL_Window *SDL_CreateWindow(const char *title, int width, int height, unsigned flags) { (void)title; (void)width; (void)height; (void)flags; return NULL; }
SDL_Renderer *SDL_CreateRenderer(SDL_Window *window, const char *name) { (void)window; (void)name; return NULL; }
void SDL_DestroyRenderer(SDL_Renderer *renderer) { (void)renderer; }
void SDL_DestroyWindow(SDL_Window *window) { (void)window; }
bool SDL_PollEvent(SDL_Event *event) { (void)event; return false; }
bool SDL_SetRenderDrawColor(SDL_Renderer *r, unsigned char a, unsigned char b, unsigned char c, unsigned char d) { (void)r; (void)a; (void)b; (void)c; (void)d; return true; }
bool SDL_RenderClear(SDL_Renderer *r) { (void)r; return true; }
bool SDL_SetRenderScale(SDL_Renderer *r, float x, float y) { (void)r; (void)x; (void)y; return true; }
bool SDL_RenderDebugText(SDL_Renderer *r, float x, float y, const char *text) { (void)r; (void)x; (void)y; (void)text; return true; }
bool SDL_RenderFillRect(SDL_Renderer *r, const SDL_FRect *rect) { (void)r; (void)rect; return true; }
bool SDL_RenderPresent(SDL_Renderer *r) { (void)r; return true; }
void SDL_Delay(unsigned milliseconds) { (void)milliseconds; }

/* update.h: the files behave as posix_update.c's do */
int update_download(const char *url, const char *path, update_progress_proc progress, void *context, char *error, int error_size) {
    FILE *from, *to; char buffer[4096]; size_t count; unsigned long long total = 0;
    assert(!strcmp(url, "https://github.com/pfista/halo-og/releases/download/v0.6.1/halo-linux-release.zip"));
    from = fopen(fixture_zip, "rb");
    if (!from) { snprintf(error, (size_t)error_size, "the server could not be reached"); return 0; }
    to = fopen(path, "wb"); assert(to);
    while ((count = fread(buffer, 1, sizeof(buffer), from)) > 0) { assert(fwrite(buffer, 1, count, to) == count); total += count; }
    fclose(from); fclose(to); progress(context, total, total); return 1;
}
int update_executable_path(char *path, int size) { return snprintf(path, (size_t)size, "%s/halo", game_folder) < size; }
int update_replace_file(const char *path, const char *new_path, const char *old_path) {
    struct stat information; int existed = stat(path, &information) == 0;
    const char *name = strrchr(path, '/');
    if (!strcmp(name ? name + 1 : path, unreplaceable)) return 0;
    unlink(old_path);
    if (existed && rename(path, old_path) != 0) return 0;
    if (rename(new_path, path) != 0) { if (existed) rename(old_path, path); return 0; }
    chmod(path, existed ? (information.st_mode & 07777) : 0644);
    return 1;
}
void update_delete_file(const char *path) { if (unlink(path) != 0) rmdir(path); }
int update_make_directory(const char *path) { return mkdir(path, 0755) == 0 || errno == EEXIST; }
int update_launch(const char *path) { assert(strstr(path, "/halo")); launches++; return 1; }

int main(int argc, char **argv) {
    /* install folder zip size sha256 [unreplaceable], or: start folder */
    char error[512] = "";
    unsigned char digest[32];
    struct update_install_request request = { "https://github.com/pfista/halo-og/releases/download/v0.6.1/halo-linux-release.zip", "v0.6.1", 0, digest };
    assert(argc >= 3); game_folder = argv[2];
    if (!strcmp(argv[1], "start")) return update_install_prepare() ? 0 : 1;
    assert(argc >= 6); fixture_zip = argv[3]; request.size = strtoull(argv[4], NULL, 10);
    for (unsigned i = 0; i < 32; i++) { unsigned value; assert(sscanf(argv[5] + i * 2, "%2x", &value) == 1); digest[i] = (unsigned char)value; }
    if (argc > 6) unreplaceable = argv[6];
    if (!update_install(&request, error, sizeof(error))) { printf("failed: %s\n", error); return 0; }
    assert(update_install_relaunch() && launches == 1);
    printf("installed\n");
    return 0;
}
'''

OLD = {"halo": b"previous executable", "Newtown-LICENSE.txt": b"previous license",
       "config.toml": b"the player's settings", "maps/chillout.map": b"the player's map"}
NEW = {"halo": b"new executable" * 5000, "Newtown-LICENSE.txt": b"new license", "fonts-README.md": b"a file new in this release"}


@unittest.skipIf(sys.platform == "win32", "the fixture's system side is POSIX")
class InstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise RuntimeError("A native C compiler is required for update-install tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-install-fixture-")
        cls.work = Path(cls.temporary.name)
        (cls.work / "SDL3").mkdir()
        (cls.work / "SDL3/SDL.h").write_text(SDL)
        # The game's bundled zlib is replaced by the system's, which has the same interface.
        (cls.work / "memory/zlib").mkdir(parents=True)
        (cls.work / "memory/zlib/zlib.h").write_text("#include <zlib.h>\n")
        (cls.work / "fixture.c").write_text(HARNESS)
        cls.binary = cls.work / "fixture"
        subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-I" + str(cls.work), "-I" + str(ROOT / "port/linux/src"),
                        str(cls.work / "fixture.c"), "-lz", "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(dir=self.work, prefix="game-"))
        for name, data in OLD.items():
            (self.folder / name).parent.mkdir(parents=True, exist_ok=True)
            (self.folder / name).write_bytes(data)
        (self.folder / "halo").chmod(0o755)
        self.zip = self.work / "release.zip"
        self.package(NEW)

    def package(self, files):
        with zipfile.ZipFile(self.zip, "w") as archive:
            for index, (name, data) in enumerate(files.items()):
                archive.writestr(name, data, zipfile.ZIP_STORED if index % 2 else zipfile.ZIP_DEFLATED)

    def install(self, *extra, size=None, digest=None):
        data = self.zip.read_bytes() if self.zip.exists() else b""
        command = [str(self.binary), "install", str(self.folder), str(self.zip),
                   str(len(data) if size is None else size), digest or hashlib.sha256(data).hexdigest(), *extra]
        return subprocess.check_output(command, text=True).strip()

    def contents(self):
        return {str(path.relative_to(self.folder)): path.read_bytes()
                for path in sorted(self.folder.rglob("*")) if path.is_file()}

    def test_update_replaces_the_release_files_and_keeps_the_previous_version_until_the_next_start(self):
        self.assertEqual(self.install(), "installed")
        self.assertEqual(self.contents(), {
            **NEW, "halo.old": OLD["halo"], "Newtown-LICENSE.txt.old": OLD["Newtown-LICENSE.txt"],
            "config.toml": OLD["config.toml"], "maps/chillout.map": OLD["maps/chillout.map"],
            "update-replaced.txt": b"halo\nNewtown-LICENSE.txt\nfonts-README.md\n"})
        self.assertTrue((self.folder / "halo").stat().st_mode & 0o100)
        # The new version starting is what shows the previous one is no longer needed.
        subprocess.run([str(self.binary), "start", str(self.folder)], check=True)
        self.assertEqual(self.contents(), {**NEW, "config.toml": OLD["config.toml"],
                                           "maps/chillout.map": OLD["maps/chillout.map"]})

    def test_a_download_that_is_not_the_published_file_changes_nothing(self):
        data = self.zip.read_bytes()
        for name, arguments in (("another file's hash", {"digest": hashlib.sha256(b"other").hexdigest()}),
                                ("another size", {"size": len(data) + 1})):
            with self.subTest(name=name):
                self.assertIn("not the file this release was published with", self.install(**arguments))
                self.assertEqual(self.contents(), OLD)
        self.zip.write_bytes(data[:len(data) // 2])
        self.assertIn("failed:", self.install())
        self.assertEqual(self.contents(), OLD)
        self.zip.unlink()
        self.assertEqual(self.install(), "failed: the server could not be reached")
        self.assertEqual(self.contents(), OLD)

    def test_a_file_that_cannot_be_replaced_puts_the_previous_version_back(self):
        # Whichever file fails, and in either order, no file of the new version
        # stays beside the old ones: not even one the previous version did not have.
        for files in (NEW, dict(reversed(NEW.items()))):
            self.package(files)
            for name in files:
                with self.subTest(order=list(files), unreplaceable=name):
                    self.assertIn("could not replace", self.install(name))
                    self.assertEqual(self.contents(), OLD)
                    self.assertTrue((self.folder / "halo").stat().st_mode & 0o100)

    def test_a_package_never_replaces_settings_or_writes_outside_the_game_folder(self):
        self.package({**NEW, "config.toml": b"a release's defaults", "maps/chillout.map": b"a release's map",
                      "../escaped.txt": b"outside", "nested/halo": b"a path"})
        self.assertEqual(self.install(), "installed")
        files = self.contents()
        self.assertEqual(files["config.toml"], OLD["config.toml"])
        self.assertEqual(files["maps/chillout.map"], OLD["maps/chillout.map"])
        self.assertNotIn("nested/halo", files)
        self.assertFalse((self.folder.parent / "escaped.txt").exists())


if __name__ == "__main__":
    unittest.main()
