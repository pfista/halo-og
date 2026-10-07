"""Compile the production desktop prefetcher against isolated, network-free I/O.

The bounded TLS transport is stubbed; parsing, stock/cache checks, streaming
SHA-256, filesystem safety and exclusive publication are the actual C module.
No app, original game asset, user setting or network connection is involved.
"""
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

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/community_maps_download.c"
MAX_MAP = 512 * 1024 * 1024

SDL_HEADER = r'''
#ifndef SDL_TEST_STUB
#define SDL_TEST_STUB
#include <stdint.h>
typedef struct { int value; } SDL_AtomicInt;
typedef struct { int unused; } SDL_Thread;
int SDL_CompareAndSwapAtomicInt(SDL_AtomicInt *, int, int);
SDL_Thread *SDL_CreateThread(int (*)(void *), const char *, void *);
void SDL_DetachThread(SDL_Thread *);
const char *SDL_GetError(void);
uint64_t SDL_GetTicksNS(void);
#endif
'''
HARNESS = r'''
#include <SDL3/SDL.h>
#include "community_maps_download.h"
#include "update.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef _WIN32
#undef link
#undef fsync
#include <unistd.h>
#include <errno.h>
#endif
static const char *root, *fixtures, *mode;
static unsigned calls, map_calls;
static unsigned long long ticks;
int config_boolean(const char *name) { return !strcmp(name, "community_maps.auto_download") && strcmp(mode, "disabled"); }
const char *platform_data_root(void) { return root; }
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
static int copy(const char *source, const char *target, unsigned long long cap,
                update_progress_proc progress, void *context, int partial) {
    FILE *input = fopen(source, "rb"), *output;
    unsigned char bytes[16384]; size_t count; unsigned long long received = 0, total;
    if (!input) return 0;
    fseek(input, 0, SEEK_END); total = (unsigned long long)ftell(input); rewind(input);
    output = fopen(target, "wb"); if (!output) { fclose(input); return 0; }
    while ((count = fread(bytes, 1, sizeof(bytes), input))) {
        if (count > cap - received) { fclose(output); fclose(input); return 0; }
        if (fwrite(bytes, 1, count, output) != count) { fclose(output); fclose(input); return 0; }
        received += count;
        if (progress) progress(context, received, total);
        if (partial) { fclose(output); fclose(input); return 0; }
    }
    int result = !ferror(input) && fclose(output) == 0; fclose(input); return result;
}
#ifndef _WIN32
int desktop_test_link(const char *source, const char *target) {
    if (!strcmp(mode, "publish-failure")) { errno = ENOSPC; return -1; }
    if (!strcmp(mode, "link-race")) {
        FILE *file = fopen(target, "wb"); if (!file) abort(); fputs("publication race winner", file); fclose(file);
    }
    return link(source, target);
}
int desktop_test_fsync(int file) {
    if (!strcmp(mode, "flush-failure")) { errno = ENOSPC; return -1; }
    return fsync(file);
}
#endif
int update_download_limited(const char *url, const char *target, unsigned long long cap,
    update_progress_proc progress, void *context, char *error, int error_size) {
    char source[2048], name[128], raced[2048]; int catalog = strstr(url, "/catalogs/testing/current.json") != NULL;
    calls++;
    if (strncmp(url, "https://dl.oghalo.com/", strlen("https://dl.oghalo.com/")) || !cap) abort();
    if (catalog) {
        if (cap != 1048576) abort();
        snprintf(source, sizeof(source), "%s/catalog.json", fixtures);
    } else {
        const char *encoded = strrchr(url, '/') + 1; size_t length = 0;
        while (*encoded && length + 1 < sizeof(name)) {
            if (!strncmp(encoded, "%20", 3)) { name[length++] = ' '; encoded += 3; }
            else name[length++] = *encoded++;
        }
        name[length] = 0; map_calls++;
        snprintf(source, sizeof(source), "%s/%s", fixtures, name);
        if (!strcmp(mode, "race") || !strcmp(mode, "race-exact")) {
            snprintf(raced, sizeof(raced), "%s/maps/%s", root, name);
            if (!strcmp(mode, "race")) { FILE *file = fopen(raced, "wb"); if (!file) abort(); fputs("racing user bytes", file); fclose(file); }
            else if (!copy(source, raced, cap, NULL, NULL, 0)) abort();
        }
    }
    int result = copy(source, target, cap, progress, context, !catalog && !strcmp(mode, "fail-map"));
    if (!result) snprintf(error, error_size, "fixture transport refused incomplete/oversized body");
    return result;
}
int main(int count, char **arguments) {
    if (count != 4) return 2; root = arguments[1]; fixtures = arguments[2]; mode = arguments[3];
    community_maps_download_start(); community_maps_download_start();
    printf("requests=%u maps=%u\n", calls, map_calls); return 0;
}
'''


def cache(name, kind=1, declared=4096, tags=64, offset=2048, build="01.10.12.2276", version=5):
    data = bytearray(2048 + 101)
    data[:4] = b"daeh"
    struct.pack_into("<I", data, 4, version)
    struct.pack_into("<I", data, 8, declared)
    struct.pack_into("<II", data, 16, offset, tags)
    data[32:32 + len(name)] = name.encode("ascii")
    data[64:64 + len(build)] = build.encode("ascii")
    struct.pack_into("<H", data, 96, kind)
    data[2044:2048] = b"toof"
    data[2048:] = b"synthetic authored cache fixture!" * 3 + b"dummy"
    return bytes(data)


def entry(name, data):
    sha = hashlib.sha256(data).hexdigest()
    return {"id": name, "sha256": sha, "file_bytes": len(data), "cache_version": 5,
            "cache_build": "01.10.12.2276", "scenario_type": 1,
            "object_key": f"maps/sha256/{sha}/{name}.map", "prefetch": True}


@unittest.skipUnless(shutil.which("clang"), "clang required for production native fixture")
class DesktopMapDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="halo-og-map-native-")
        build = Path(cls.build.name)
        (build / "SDL3").mkdir()
        (build / "SDL3/SDL.h").write_text(SDL_HEADER)
        (build / "harness.c").write_text(HARNESS)
        cls.binary = build / ("prefetch.exe" if sys.platform == "win32" else "prefetch")
        command = [shutil.which("clang"), "-std=c11", "-Werror", "-Wall", "-Wextra", "-D_GNU_SOURCE",
                   "-I" + str(build), "-I" + str(ROOT / "port/linux/src"), str(SOURCE), str(build / "harness.c")]
        if sys.platform == "win32":
            command += ["-D_CRT_SECURE_NO_WARNINGS", "-lbcrypt", "-ladvapi32"]
        else:
            mbed = ROOT / "port/third_party/mbedtls"
            (build / "sha-config.h").write_text("#define MBEDTLS_SHA256_C\n")
            command += ['-DMBEDTLS_CONFIG_FILE="sha-config.h"', "-I" + str(mbed / "include"),
                        "-I" + str(mbed / "library"), str(mbed / "library/sha256.c"),
                        str(mbed / "library/platform_util.c"), "-Dlink=desktop_test_link", "-Dfsync=desktop_test_fsync",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        command += ["-o", str(cls.binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-og-maps-test-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.data, self.fixtures = base / "game data", base / "fixtures"
        (self.data / "maps").mkdir(parents=True)
        self.fixtures.mkdir()
        self.stock = {}
        for name, kind in (("bloodgulch", 1), ("a10", 0), ("ui", 2)):
            data = cache(name, kind)
            (self.data / "maps" / (name + ".map")).write_bytes(data)
            self.stock[name] = data
        self.map = cache("authored")
        (self.fixtures / "authored.map").write_bytes(self.map)
        self.catalog = {"schema_version": 1, "profile": "stock-xbox-ntsc", "maps": [entry("authored", self.map)]}

    def run_fixture(self, mode="normal", raw=None, data_root=None):
        (self.fixtures / "catalog.json").write_bytes(raw if raw is not None else json.dumps(self.catalog).encode())
        result = subprocess.run([str(self.binary), str(data_root or self.data), str(self.fixtures), mode],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list((self.data / "maps").glob(".halo-og-download-*")), "private partial directories must be removed")
        for name, expected in self.stock.items():
            target = self.data / "maps" / (name + ".map")
            if target.exists() and not target.is_symlink(): self.assertEqual(target.read_bytes(), expected)
        return result

    def test_exact_compressed_map_published_once_and_encoded_spaces(self):
        named = cache("authored map")
        (self.fixtures / "authored map.map").write_bytes(named)
        self.catalog["maps"].append(entry("authored map", named))
        result = self.run_fixture()
        self.assertIn("requests=3 maps=2", result.stdout)
        self.assertEqual((self.data / "maps/authored.map").read_bytes(), self.map)
        self.assertEqual((self.data / "maps/authored map.map").read_bytes(), named)
        self.assertIn("Restart Halo OG", result.stderr)

    def test_existing_bytes_case_alias_and_exact_replay_never_download(self):
        target = self.data / "maps/AUTHORED.MAP"
        target.write_bytes(b"user map must win")
        result = self.run_fixture()
        self.assertIn("requests=1 maps=0", result.stdout)
        self.assertEqual(target.read_bytes(), b"user map must win")
        self.assertNotIn("authored.map", [item.name for item in (self.data / "maps").iterdir()])
        target.unlink()
        (self.data / "maps/authored.map").write_bytes(self.map)
        result = self.run_fixture()
        self.assertIn("requests=1 maps=0", result.stdout)
        self.assertIn("already verified", result.stderr)

    def test_racing_file_preserved_and_matching_race_accepted(self):
        result = self.run_fixture("race")
        target = self.data / "maps/authored.map"
        self.assertEqual(target.read_bytes(), b"racing user bytes")
        self.assertIn("existing content preserved", result.stderr)
        target.unlink()
        result = self.run_fixture("race-exact")
        self.assertEqual(target.read_bytes(), self.map)
        self.assertIn("1 verified", result.stderr)

    def test_exclusive_link_and_flush_failure_preserve_final_boundary(self):
        if sys.platform == "win32": self.skipTest("POSIX link/fsync fault injection; Windows exercises native exclusive hard-link success")
        result = self.run_fixture("link-race")
        target = self.data / "maps/authored.map"
        self.assertEqual(target.read_bytes(), b"publication race winner")
        self.assertIn("existing content preserved", result.stderr)
        target.unlink()
        result = self.run_fixture("flush-failure")
        self.assertFalse(target.exists())
        self.assertIn("failed exact", result.stderr)
        result = self.run_fixture("publish-failure")
        self.assertFalse(target.exists())
        self.assertIn("0 existing files preserved, 1 failed", result.stderr)
        self.assertIn("could not be published safely", result.stderr)

    def test_config_off_and_wrong_stock_profile_make_no_requests(self):
        self.assertIn("requests=0", self.run_fixture("disabled").stdout)
        target = self.data / "maps/ui.map"
        bad = cache("ui", 2, build="01.00.00.0000")
        target.write_bytes(bad); self.stock["ui"] = bad
        self.assertIn("requests=0", self.run_fixture().stdout)

    def test_case_compatible_stock_directory(self):
        upper = self.data / "MAPS"
        (self.data / "maps").rename(upper)
        (upper / "ui.map").rename(upper / "UI.MAP")
        result = self.run_fixture()
        self.assertIn("requests=2", result.stdout)
        self.assertEqual((upper / "authored.map").read_bytes(), self.map)

    def test_symlink_stock_destination_and_data_ancestor_refused(self):
        if sys.platform == "win32": self.skipTest("Windows symlink privilege varies; native reparse code runs in Windows fixtures")
        outside = Path(self.temp.name) / "outside.map"
        outside.write_bytes(b"unrelated bytes")
        target = self.data / "maps/authored.map"
        target.symlink_to(outside)
        result = self.run_fixture()
        self.assertIn("requests=1 maps=0", result.stdout)
        self.assertEqual(outside.read_bytes(), b"unrelated bytes")
        target.unlink()
        stock = self.data / "maps/ui.map"
        stock.unlink(); stock.symlink_to(outside)
        self.assertIn("requests=0", self.run_fixture().stdout)
        stock.unlink(); stock.write_bytes(self.stock["ui"])
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.data, target_is_directory=True)
        self.assertIn("requests=0", self.run_fixture(data_root=alias).stdout)

    def test_catalog_malformed_duplicate_unknown_and_limits_rejected_before_maps(self):
        changes = []
        for key, value in (("id", "../bad"), ("id", "bloodgulch"), ("id", "con"), ("id", "trailing "),
                           ("id", "UPPER"), ("sha256", "a" * 63), ("file_bytes", True), ("file_bytes", 1.5),
                           ("file_bytes", MAX_MAP + 1), ("cache_version", 7), ("scenario_type", 2),
                           ("cache_build", "01.00.00.0000"), ("object_key", "https://other.host/map"),
                           ("prefetch", 1), ("unknown", "ignored")):
            changed = copy.deepcopy(self.catalog); changed["maps"][0][key] = value; changes.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.catalog); changed["maps"] *= 2; changes.append(json.dumps(changed).encode())
        changed = copy.deepcopy(self.catalog); changed["profile"] = "pal"; changes.append(json.dumps(changed).encode())
        for count, size in ((116, len(self.map)), (17, MAX_MAP)):
            changed = copy.deepcopy(self.catalog)
            changed["maps"] = []
            for index in range(count):
                item = entry("authored" + str(index), self.map)
                item["file_bytes"] = size
                changed["maps"].append(item)
            changes.append(json.dumps(changed).encode())
        changes += [b'{"schema_version":1,"schema_version":1,"profile":"stock-xbox-ntsc","maps":[]}',
                    json.dumps(self.catalog).encode() + b" garbage", b"{}", b"x" * (1048576 + 1)]
        for raw in changes:
            with self.subTest(raw=raw[:90]):
                result = self.run_fixture(raw=raw)
                self.assertIn("maps=0", result.stdout)
                self.assertFalse((self.data / "maps/authored.map").exists())

    def test_large_declared_multiplayer_headers_keep_small_streamed_transfers(self):
        # Disk size and declared/uncompressed cache size are distinct. These
        # bounded fixtures exercise the production header acceptance without
        # allocating or downloading a hundreds-of-megabytes body.
        for name, declared in (("large-authored", 150 * 1024 * 1024),
                               ("limit-authored", MAX_MAP)):
            with self.subTest(declared=declared):
                data = cache(name, declared=declared)
                (self.fixtures / (name + ".map")).write_bytes(data)
                self.catalog["maps"] = [entry(name, data)]
                result = self.run_fixture()
                self.assertIn("requests=2 maps=1", result.stdout)
                self.assertEqual((self.data / "maps" / (name + ".map")).read_bytes(), data)

    def test_exact_transfer_ceiling_accepts_catalog_but_short_body_never_publishes(self):
        self.catalog["maps"][0]["file_bytes"] = MAX_MAP
        result = self.run_fixture()
        self.assertIn("requests=2 maps=1", result.stdout)
        self.assertFalse((self.data / "maps/authored.map").exists())
        self.assertIn("failed exact size", result.stderr)

    def test_hash_size_header_and_tag_bound_failures_publish_nothing(self):
        for mutation in ("sha", "short", "long", "pal", "campaign", "tag-offset", "tag-range", "tag-limit", "declared-limit", "magic"):
            with self.subTest(mutation=mutation):
                data = bytearray(self.map)
                if mutation == "sha": data[-1] ^= 1
                elif mutation == "short": data = data[:-1]
                elif mutation == "long": data += b"x"
                elif mutation == "pal": data[64:96] = b"wrong build".ljust(32, b"\0")
                elif mutation == "campaign": struct.pack_into("<H", data, 96, 0)
                elif mutation == "tag-offset": struct.pack_into("<I", data, 16, 2047)
                elif mutation == "tag-range": struct.pack_into("<I", data, 16, 4090)
                elif mutation == "tag-limit": struct.pack_into("<II", data, 16, 2048, 22 * 1024 * 1024 + 1)
                elif mutation == "declared-limit": struct.pack_into("<I", data, 8, MAX_MAP + 1)
                elif mutation == "magic": data[0] ^= 1
                (self.fixtures / "authored.map").write_bytes(data)
                # Authenticate malformed header bytes to exercise compatibility
                # separately from SHA mismatch. Transfer short/long keep pins.
                self.catalog["maps"][0] = entry("authored", bytes(data)) if mutation not in ("sha", "short", "long") else entry("authored", self.map)
                result = self.run_fixture()
                self.assertFalse((self.data / "maps/authored.map").exists())
                self.assertIn("failed", result.stderr)

    def test_partial_transfer_cleaned_without_publishing(self):
        result = self.run_fixture("fail-map")
        self.assertFalse((self.data / "maps/authored.map").exists())
        self.assertIn("download failed", result.stderr)

    def test_mac_android_compile_to_dependency_free_noop(self):
        build = Path(self.build.name)
        harness = build / "guard.c"
        harness.write_text('#include "community_maps_download.h"\nint main(void) { community_maps_download_start(); return 0; }\n')
        for guard in ("HALO_MACOS", "HALO_ANDROID"):
            with self.subTest(guard=guard):
                target = build / (guard + (".exe" if sys.platform == "win32" else ""))
                # No SDL, TLS, config, root or logging implementation is linked.
                # Any desktop behavior/import escaping this guard fails linking.
                result = subprocess.run([shutil.which("clang"), "-std=c11", "-Werror", "-D" + guard,
                                         "-I" + str(ROOT / "port/linux/src"), str(SOURCE), str(harness), "-o", str(target)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_config_defaults_on_and_existing_false_is_honored(self):
        # Reuse the established real-TOML fixture; no source-pattern assertion
        # and no changes to actual settings. The full downloader fixture above
        # separately executes its native Windows API branch on Windows CI.
        from tools.test_game_settings import CONFIG_HARNESS, PREFIX, SDL
        if sys.platform == "win32" or not (SDL / "include/SDL3/SDL.h").exists():
            self.skipTest("Existing real-config fixture requires POSIX SDL headers")
        build = Path(self.build.name)
        prefix, probe, binary = build / "config-prefix.h", build / "config-probe.c", build / "config-probe"
        prefix.write_text(PREFIX)
        probe.write_text(CONFIG_HARNESS.replace("audio.menu_music", "community_maps.auto_download"))
        result = subprocess.run([shutil.which("clang"), "-std=gnu11", "-Werror", "-pthread", "-include", str(prefix),
                                 "-I" + str(ROOT / "port/linux/src"), "-I" + str(SDL / "include"),
                                 "-I" + str(ROOT / "port/third_party/tomlc17"), str(probe),
                                 str(ROOT / "port/linux/src/port_config.c"), str(ROOT / "port/third_party/tomlc17/tomlc17.c"),
                                 "-o", str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        directory = Path(self.temp.name).resolve() / "config"
        directory.mkdir()
        environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
        environment.update(HALO_SAVE_ROOT=str(directory), HALO_DATA_ROOT=str(directory))
        def read():
            result = subprocess.run([str(binary), "read", "unused", "community_maps.auto_download", "0"],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout.strip()
        self.assertEqual(read(), "1")
        config = directory / "config.toml"
        self.assertTrue(tomllib.loads(config.read_text())["community_maps"]["auto_download"])
        configured = '# player choice\n[community_maps]\nauto_download = false\n[display]\nvsync = false\n'
        config.write_text(configured)
        self.assertEqual(read(), "0")
        parsed = tomllib.loads(config.read_text())
        self.assertFalse(parsed["community_maps"]["auto_download"])
        self.assertFalse(parsed["display"]["vsync"])
        self.assertTrue(config.read_text().startswith(configured))
        # Production config fills missing defaults while preserving this choice.
        complete = config.read_text()
        self.assertEqual(read(), "0")
        self.assertEqual(config.read_text(), complete)


if __name__ == "__main__":
    unittest.main()
