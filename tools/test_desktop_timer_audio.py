"""Execute Windows/Linux timer prefetch C against authored offline fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import unittest

from tools.import_performance_audio import CUES, canonical_wav
from tools.test_desktop_map_downloads import SDL_HEADER

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/timer_audio_download.c"
HARNESS = r'''
#include <SDL3/SDL.h>
#include "timer_audio_download.h"
#include "update.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#undef fsync
#undef syscall
#undef renamex_np
#include <errno.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__linux__)
#include <sys/syscall.h>
#endif
#endif
static const char *root, *fixtures, *mode;
static unsigned calls, clips;
static unsigned long long ticks;
int config_boolean(const char *name) { return !strcmp(name, "timer_audio.auto_download") && strcmp(mode, "disabled"); }
const char *platform_save_root(void) { return root; }
void platform_log(const char *format, ...) {
 va_list arguments; va_start(arguments, format); vfprintf(stderr, format, arguments); va_end(arguments); fputc('\n', stderr);
}
int SDL_CompareAndSwapAtomicInt(SDL_AtomicInt *value, int old, int next) {
 if (value->value != old) return 0; value->value = next; return 1;
}
SDL_Thread *SDL_CreateThread(int (*function)(void *), const char *name, void *context) {
 static SDL_Thread thread; (void)name; function(context); return &thread;
}
void SDL_DetachThread(SDL_Thread *thread) { (void)thread; }
const char *SDL_GetError(void) { return "test fixture"; }
uint64_t SDL_GetTicksNS(void) { return ++ticks; }
static int copy_file(const char *source, const char *target, unsigned long long cap, int partial) {
 FILE *input = fopen(source, "rb"), *output;
 unsigned char bytes[16384]; size_t count; unsigned long long received = 0;
 if (!input) return 0;
 output = fopen(target, "wb"); if (!output) { fclose(input); return 0; }
 while ((count = fread(bytes, 1, sizeof(bytes), input))) {
  if (count > cap - received) { fclose(output); fclose(input); return 0; }
  if (fwrite(bytes, 1, count, output) != count) { fclose(output); fclose(input); return 0; }
  received += count;
  if (partial) { fclose(output); fclose(input); return 0; }
 }
 int result = !ferror(input) && fclose(output) == 0; fclose(input); return result;
}
#ifndef _WIN32
static void race_folder(const char *target) {
 char path[2048];
 if (mkdir(target, 0700)) abort();
 snprintf(path, sizeof(path), "%s/keep.wav", target);
 FILE *file = fopen(path, "wb"); if (!file) abort(); fputs("racing user bytes", file); fclose(file);
}
static int before_publish(const char *target) {
 if (!strcmp(mode, "publish-failure")) { errno = ENOSPC; return 0; }
 if (!strcmp(mode, "publish-race")) race_folder(target);
 return 1;
}
#if defined(__linux__)
long desktop_timer_test_syscall(long number, ...) {
 if (number != SYS_renameat2) abort();
 va_list arguments; va_start(arguments, number);
 int sourcefd = va_arg(arguments, int); const char *source = va_arg(arguments, const char *);
 int targetfd = va_arg(arguments, int); const char *target = va_arg(arguments, const char *);
 int flags = va_arg(arguments, int); va_end(arguments);
 if (!before_publish(target)) return -1;
 return syscall(number, sourcefd, source, targetfd, target, flags);
}
#elif defined(__APPLE__)
int desktop_timer_test_renamex(const char *source, const char *target, unsigned flags) {
 if (!before_publish(target)) return -1;
 return renameatx_np(AT_FDCWD, source, AT_FDCWD, target, flags);
}
#endif
int desktop_timer_test_fsync(int file) {
 if (!strcmp(mode, "flush-failure")) { errno = ENOSPC; return -1; }
 return fsync(file);
}
#endif
int update_download_limited(const char *url, const char *target, unsigned long long cap,
 update_progress_proc progress, void *context, char *error, int error_size) {
 (void)progress; (void)context;
 char source[2048]; int manifest = !strcmp(url, "https://dl.oghalo.com/audio/timer/v1/current.json");
 calls++;
 if (strncmp(url, "https://dl.oghalo.com/", strlen("https://dl.oghalo.com/")) || !cap) abort();
 if (manifest) {
  if (cap != 65536) abort();
  snprintf(source, sizeof(source), "%s/manifest.json", fixtures);
 } else {
  const char *name = strrchr(url, '/') + 1; clips++;
  snprintf(source, sizeof(source), "%s/%s", fixtures, name);
  if (!strcmp(mode, "race") && clips == 46) {
   char pack[2048], sentinel[2048]; snprintf(pack, sizeof(pack), "%s/sounds/performance", root);
#ifdef _WIN32
   if (_mkdir(pack)) abort();
#else
   if (mkdir(pack, 0700)) abort();
#endif
   snprintf(sentinel, sizeof(sentinel), "%s/keep.wav", pack);
   FILE *file = fopen(sentinel, "wb"); if (!file) abort(); fputs("racing user bytes", file); fclose(file);
  }
 }
 int result = copy_file(source, target, cap, !manifest && clips == 46 && !strcmp(mode, "fail-last"));
 if (!result) snprintf(error, error_size, "fixture refused partial/missing/oversized body");
 return result;
}
int main(int count, char **arguments) {
 if (count != 4) return 2; root = arguments[1]; fixtures = arguments[2]; mode = arguments[3];
 timer_audio_download_start(); timer_audio_download_start();
 printf("requests=%u clips=%u\n", calls, clips); return 0;
}
'''


def entry(cue, wav):
    digest = hashlib.sha256(wav).hexdigest()
    return {"cue": cue, "file_bytes": len(wav), "sha256": digest,
            "object_key": f"audio/timer/sha256/{digest}/{cue}.wav"}


class DesktopTimerAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required for production C fixture")
        cls.build = tempfile.TemporaryDirectory(prefix="desktop-timer-build-")
        build = Path(cls.build.name)
        (build / "SDL3").mkdir()
        (build / "SDL3/SDL.h").write_text(SDL_HEADER)
        (build / "harness.c").write_text(HARNESS)
        cls.binary = build / ("timer.exe" if sys.platform == "win32" else "timer")
        command = [shutil.which("clang"), "-std=c11", "-Werror", "-Wall", "-Wextra", "-D_GNU_SOURCE",
                   "-I" + str(build), "-I" + str(ROOT / "port/linux/src"), str(SOURCE), str(build / "harness.c")]
        if sys.platform == "win32":
            command += ["-D_CRT_SECURE_NO_WARNINGS", "-lbcrypt", "-ladvapi32", "-include", "direct.h"]
        else:
            mbed = ROOT / "port/third_party/mbedtls"
            (build / "sha-config.h").write_text("#define MBEDTLS_SHA256_C\n")
            command += ['-DMBEDTLS_CONFIG_FILE="sha-config.h"', "-I" + str(mbed / "include"),
                        "-I" + str(mbed / "library"), str(mbed / "library/sha256.c"),
                        str(mbed / "library/platform_util.c"), "-Dfsync=desktop_timer_test_fsync",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command += ["-Dsyscall=desktop_timer_test_syscall"] if sys.platform.startswith("linux") else ["-Drenamex_np=desktop_timer_test_renamex"]
        command += ["-o", str(cls.binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="desktop-timer-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.save, self.fixtures = base / "saves", base / "fixtures"
        self.save.mkdir(); self.fixtures.mkdir()
        self.wav = canonical_wav(22050, 1, b"\x12\x00" * 64)
        for cue in CUES:
            (self.fixtures / (cue + ".wav")).write_bytes(self.wav)
        self.manifest = {"schema_version": 1, "pack_id": "performance-timer-v1", "files": [entry(cue, self.wav) for cue in CUES]}

    def run_fixture(self, mode="normal", raw=None, save_root=None):
        (self.fixtures / "manifest.json").write_bytes(raw if raw is not None else json.dumps(self.manifest).encode())
        result = subprocess.run([str(self.binary), str(save_root or self.save), str(self.fixtures), mode], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(list((self.save / "sounds").glob(".halo-timer-download-*")))
        return result

    def test_complete_pack_installs_once_and_existing_pack_stays_offline(self):
        result = self.run_fixture()
        pack = self.save / "sounds/performance"
        self.assertIn("requests=47 clips=46", result.stdout)
        self.assertEqual({path.name for path in pack.iterdir()}, {cue + ".wav" for cue in CUES} | {"download-manifest.json"})
        for cue in CUES:
            self.assertEqual((pack / (cue + ".wav")).read_bytes(), self.wav)
        self.assertIn("Restart Halo OG", result.stderr)
        self.assertIn("requests=0", self.run_fixture().stdout)

    def test_disabled_and_existing_partial_file_or_case_folder_preserve_bytes(self):
        self.assertIn("requests=0", self.run_fixture("disabled").stdout)
        sounds = self.save / "sounds"; sounds.mkdir()
        pack = sounds / "performance"
        pack.write_bytes(b"user file")
        self.assertIn("requests=0", self.run_fixture().stdout)
        self.assertEqual(pack.read_bytes(), b"user file")
        pack.unlink(); pack.mkdir()
        (pack / "keep.wav").write_bytes(b"user partial pack")
        self.assertIn("requests=0", self.run_fixture().stdout)
        self.assertEqual((pack / "keep.wav").read_bytes(), b"user partial pack")
        pack.rename(sounds / "PERFORMANCE")
        self.assertIn("requests=0", self.run_fixture().stdout)
        self.assertEqual((sounds / "PERFORMANCE/keep.wav").read_bytes(), b"user partial pack")

    def test_last_transfer_hash_and_pcm_failures_never_activate_partial_pack(self):
        for mutation in ("sha", "short", "long", "pcm", "rate", "align", "riff", "tail", "empty"):
            with self.subTest(mutation=mutation):
                damaged = bytearray(self.wav)
                if mutation == "sha": damaged[-1] ^= 1
                elif mutation == "short": damaged = damaged[:-1]
                elif mutation == "long": damaged += b"x"
                elif mutation == "pcm": struct.pack_into("<H", damaged, 20, 3)
                elif mutation == "rate": struct.pack_into("<I", damaged, 24, 48000)
                elif mutation == "align": struct.pack_into("<H", damaged, 32, 4)
                elif mutation == "riff": damaged[0] ^= 1
                elif mutation == "tail": damaged += b"junk"
                else: damaged = bytearray(canonical_wav(22050, 1, b""))
                (self.fixtures / "overshield.wav").write_bytes(damaged)
                self.manifest["files"][-1] = entry("overshield", bytes(damaged)) if mutation not in ("sha", "short", "long", "empty") else entry("overshield", self.wav)
                result = self.run_fixture()
                self.assertFalse((self.save / "sounds/performance").exists())
                self.assertIn("failed", result.stderr)
        (self.fixtures / "overshield.wav").write_bytes(self.wav)
        self.manifest["files"][-1] = entry("overshield", self.wav)
        self.assertIn("download failed", self.run_fixture("fail-last").stderr)
        self.assertFalse((self.save / "sounds/performance").exists())

    def test_strict_manifest_rejected_before_any_recording_request(self):
        changes = []
        for key, value in (("cue", "../outside"), ("cue", "TimerBeep"), ("sha256", "a" * 63),
                           ("file_bytes", True), ("file_bytes", 172.0), ("file_bytes", 1048577),
                           ("object_key", "maps/other.map"), ("unknown", 1)):
            changed = copy.deepcopy(self.manifest); changed["files"][0][key] = value; changes.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.manifest); changed["files"].pop(); changes.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.manifest); changed["files"][-1] = changed["files"][0]; changes.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.manifest)
        for item in changed["files"]: item["file_bytes"] = 1048576
        changes.append(json.dumps(changed).encode())
        raw = json.dumps(self.manifest).encode()
        changes += [raw + b"garbage", raw.replace(b'"schema_version": 1', b'"schema_version": 1, "schema_version": 1'), b"{}", b"x" * 65537]
        for raw in changes:
            with self.subTest(raw=raw[:100]):
                result = self.run_fixture(raw=raw)
                self.assertIn("clips=0", result.stdout)
                self.assertFalse((self.save / "sounds/performance").exists())

    def test_racing_user_folder_wins_after_last_clip(self):
        result = self.run_fixture("race")
        pack = self.save / "sounds/performance"
        self.assertEqual(list(pack.iterdir()), [pack / "keep.wav"])
        self.assertEqual((pack / "keep.wav").read_bytes(), b"racing user bytes")
        self.assertIn("could not be activated", result.stderr)

    def test_exclusive_publication_and_flush_failures_preserve_boundary(self):
        if sys.platform == "win32": self.skipTest("POSIX publication/flush injection; Windows uses actual exclusive MoveFileEx")
        for mode in ("publish-failure", "flush-failure"):
            self.run_fixture(mode)
            self.assertFalse((self.save / "sounds/performance").exists())
        self.run_fixture("publish-race")
        self.assertEqual((self.save / "sounds/performance/keep.wav").read_bytes(), b"racing user bytes")

    def test_symlink_root_sounds_and_existing_pack_never_followed(self):
        if sys.platform == "win32": self.skipTest("Windows symlink privilege varies; production checks native reparse flags")
        outside = Path(self.temp.name).resolve() / "outside"; outside.mkdir()
        alias = Path(self.temp.name).resolve() / "alias"; alias.symlink_to(self.save, target_is_directory=True)
        self.assertIn("requests=0", self.run_fixture(save_root=alias).stdout)
        sounds = self.save / "sounds"; sounds.symlink_to(outside, target_is_directory=True)
        self.assertIn("requests=0", self.run_fixture().stdout)
        self.assertEqual(list(outside.iterdir()), [])
        sounds.unlink(); sounds.mkdir()
        (sounds / "performance").symlink_to(outside, target_is_directory=True)
        self.assertIn("requests=0", self.run_fixture().stdout)
        self.assertEqual(list(outside.iterdir()), [])

    def test_mac_android_compile_to_dependency_free_noop(self):
        build = Path(self.build.name)
        harness = build / "guard.c"
        harness.write_text('#include "timer_audio_download.h"\nint main(void) { timer_audio_download_start(); return 0; }\n')
        for guard in ("HALO_MACOS", "HALO_ANDROID"):
            target = build / guard
            result = subprocess.run([shutil.which("clang"), "-std=c11", "-Werror", "-D" + guard,
                                     "-I" + str(ROOT / "port/linux/src"), str(SOURCE), str(harness), "-o", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_toml_default_true_and_saved_false(self):
        from tools.test_game_settings import CONFIG_HARNESS, PREFIX, SDL
        if sys.platform == "win32" or not (SDL / "include/SDL3/SDL.h").exists(): self.skipTest("Existing config fixture requires POSIX SDL headers")
        build = Path(self.build.name)
        prefix, probe, binary = build / "config-prefix.h", build / "config.c", build / "config"
        prefix.write_text(PREFIX)
        probe.write_text(CONFIG_HARNESS.replace("audio.menu_music", "timer_audio.auto_download"))
        result = subprocess.run([shutil.which("clang"), "-std=gnu11", "-Werror", "-pthread", "-include", str(prefix),
                                 "-I" + str(ROOT / "port/linux/src"), "-I" + str(SDL / "include"), "-I" + str(ROOT / "port/third_party/tomlc17"),
                                 str(probe), str(ROOT / "port/linux/src/port_config.c"), str(ROOT / "port/third_party/tomlc17/tomlc17.c"),
                                 "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        directory = Path(self.temp.name).resolve() / "config"; directory.mkdir()
        environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
        environment.update(HALO_SAVE_ROOT=str(directory), HALO_DATA_ROOT=str(directory))
        def read():
            result = subprocess.run([str(binary), "read", "unused", "timer_audio.auto_download", "0"], env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()
        self.assertEqual(read(), "1")
        config = directory / "config.toml"
        self.assertTrue(tomllib.loads(config.read_text())["timer_audio"]["auto_download"])
        config.write_text("# preserve choice\n[timer_audio]\nauto_download = false\n[display]\nvsync = false\n")
        self.assertEqual(read(), "0")
        self.assertFalse(tomllib.loads(config.read_text())["timer_audio"]["auto_download"])
        self.assertFalse(tomllib.loads(config.read_text())["display"]["vsync"])


if __name__ == "__main__":
    unittest.main()
