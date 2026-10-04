"""Production C parser/assembler, trusted synthetic native helpers, no network.

These fixtures exercise host filesystem and subprocess APIs on each CI OS.
They neither contain original assets nor build/install/launch a game.
"""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

from tools import community_packages as packages

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/community_packages.c"
PINS = {"binaries": json.loads((ROOT / "tools/community-toolchain/pins.json").read_text())["compatible_package_producers"][0]["tool_sha256"]}

HELPER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#define mkdir_one(p) CreateDirectoryA(p, NULL)
#else
#include <sys/stat.h>
#include <unistd.h>
#define mkdir_one(p) mkdir(p, 0700)
#endif
static void path(char *out, const char *a, const char *b) { if (snprintf(out, 4096, "%s/%s", a, b) >= 4096) exit(8); }
static int copy(const char *a, const char *b) {
    FILE *in = fopen(a, "rb"), *out = NULL; unsigned char bytes[16384]; size_t n;
    if (!in || !(out = fopen(b, "wb"))) { if (in) fclose(in); return 0; }
    while ((n = fread(bytes, 1, sizeof(bytes), in))) if (fwrite(bytes, 1, n, out) != n) exit(9);
    int okay = !ferror(in) && fclose(out) == 0; fclose(in); return okay;
}
static int equals(const char *path, const char *expected) {
    char bytes[1024]; FILE *file = fopen(path, "rb"); if (!file) return 0;
    size_t n = fread(bytes, 1, sizeof(bytes), file); fclose(file);
    return n == strlen(expected) && !memcmp(bytes, expected, n);
}
int main(int argc, char **argv) {
    char base[4096], a[4096], b[4096], mode[64] = "";
    if (strlen(argv[0]) >= sizeof(base)) return 2; strcpy(base, argv[0]);
    char *slash = strrchr(base, '/');
#ifdef _WIN32
    char *back = strrchr(base, '\\'); if (back && (!slash || back > slash)) slash = back;
#endif
    if (!slash) return 3; *slash = 0;
    path(a, base, "invocations.log"); FILE *log = fopen(a, "ab"); if (!log) return 4;
    fputs(strstr(argv[0], "extract") ? "extract\n" : "build\n", log); fclose(log);
    path(a, base, "mode"); FILE *m = fopen(a, "rb"); if (m) { fread(mode, 1, sizeof(mode) - 1, m); fclose(m); }
    if (!strcmp(mode, "fail")) return 5;
    if (strstr(argv[0], "extract")) {
        if (argc != 4 || strcmp(argv[1], "-t")) return 6;
        path(a, argv[2], "weapons"); mkdir_one(a); path(a, argv[2], "globals"); mkdir_one(a);
        path(a, base, "original-pistol"); path(b, argv[2], "weapons/pistol.weapon"); if (!copy(a, b)) return 7;
        path(a, base, "original-globals"); path(b, argv[2], "globals/globals.globals"); if (!copy(a, b)) return 7;
#ifndef _WIN32
        if (!strcmp(mode, "symlink")) { path(b, argv[2], "unsafe-link"); symlink(a, b); }
#endif
        return 0;
    }
    const char *stock = NULL, *tags = NULL, *maps = NULL, *scenario = NULL;
    for (int i = 1; i + 1 < argc; i++) {
        if (!strcmp(argv[i], "-t")) { if (!stock) stock = argv[++i]; else tags = argv[++i]; }
        else if (!strcmp(argv[i], "-m")) maps = argv[++i];
        else if (!strcmp(argv[i], "-E")) scenario = argv[++i];
    }
    if (!stock || !tags || !maps || !scenario) return 10;
    path(a, stock, "globals/globals.globals"); if (!equals(a, "whole modified globals")) return 11;
    path(a, tags, "weapons/pistol.weapon"); if (!equals(a, "whole unchanged pistol")) return 12;
    const char *id = strrchr(scenario, '/'); id = id ? id + 1 : scenario;
    char name[128]; snprintf(name, sizeof(name), "expected-%s.map", id); path(a, base, name);
    snprintf(name, sizeof(name), "%s.map", id); path(b, maps, name);
    if (!copy(a, b)) return 13;
    if (!strcmp(mode, "wrong-output")) { FILE *f = fopen(b, "ab"); fputc('!', f); fclose(f); }
    return 0;
}
'''

HARNESS = r'''
#include "community_packages.h"
#include <stdio.h>
#include <string.h>
static void progress(void *context, const char *message) { (void)context; fprintf(stderr, "%s\n", message); }
int main(int argc, char **argv) {
    char error[512] = ""; struct community_package_info info; int result;
    if (argc == 3 && !strcmp(argv[1], "inspect")) {
        result = community_package_inspect(argv[2], &info, error, sizeof(error));
        if (result >= 0) printf("id=%s sha=%s size=%llu declared=%llu tags=%llu package_bytes=%llu\n", info.id, info.map_sha256, info.map_bytes, info.declared_bytes, info.tag_bytes, info.package_bytes);
    } else if (argc == 8) result = community_package_reconstruct(argv[2], argv[3], argv[4], argv[5], argv[6], argv[7], progress, NULL, error, sizeof(error));
    else return 2;
    printf("result=%d\n", result); if (*error) fprintf(stderr, "%s\n", error); return result < 0;
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native_flags(build):
    flags = ["-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-I" + str(ROOT / "port/linux/src"),
             "-I" + str(ROOT / "port/third_party/miniz"), str(ROOT / "port/linux/src/community_mapog.c"),
             str(ROOT / "port/third_party/miniz/tinfl_only.c")]
    if sys.platform == "win32":
        flags += ["-D_CRT_SECURE_NO_WARNINGS", "-lbcrypt", "-ladvapi32"]
    elif sys.platform == "darwin":
        flags += ["-Wno-deprecated-declarations", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    else:
        mbed = ROOT / "port/third_party/mbedtls"
        (build / "sha-config.h").write_text("#define MBEDTLS_SHA256_C\n")
        flags += ['-DMBEDTLS_CONFIG_FILE="sha-config.h"', "-I" + str(build), "-I" + str(mbed / "include"),
                  "-I" + str(mbed / "library"), str(mbed / "library/sha256.c"), str(mbed / "library/platform_util.c"),
                  "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    return flags


def compressed_package(raw):
    return struct.pack("<8sQ32s", b"HOGMAP2\n", len(raw), hashlib.sha256(raw).digest()) + zlib.compress(raw, 9)


def cache(name, kind=1, declared=4096, tags=64, offset=2048):
    data = bytearray(2149)
    data[:4] = b"daeh"
    struct.pack_into("<I", data, 4, 5)
    struct.pack_into("<I", data, 8, declared)
    struct.pack_into("<II", data, 16, offset, tags)
    data[32:32 + len(name)] = name.encode()
    data[64:64 + len(packages.NTSC_BUILD)] = packages.NTSC_BUILD.encode()
    struct.pack_into("<H", data, 96, kind)
    data[2044:2048] = b"toof"
    data[2048:] = b"synthetic map fixture!" * 4 + b"." * 17
    return bytes(data)


def create_package(parent, stock_maps, name="authored", expected=None):
    parent.mkdir(parents=True, exist_ok=True)
    trees = {key: parent / key for key in ("original", "patched", "tags", "data")}
    original = {"weapons/pistol.weapon": b"whole unchanged pistol", "globals/globals.globals": b"original globals"}
    patched = dict(original, **{"globals/globals.globals": b"whole modified globals"})
    authored = {"weapons/pistol.weapon": original["weapons/pistol.weapon"],
                f"levels/test/{name}/{name}.scenario": b"whole authored scenario", "custom/texture.bitmap": b"custom texture bytes"}
    for tree, files in (("original", original), ("patched", patched), ("tags", authored), ("data", {"cleanup.hsc": b"(script startup cleanup)"})):
        trees[tree].mkdir()
        for relative, data in files.items():
            path = trees[tree] / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    producer = parent / "producer.json"
    producer.write_text(json.dumps({"invader_commit": packages.INVADER_COMMIT,
        "binaries": {key: {"sha256": value} for key, value in PINS["binaries"].items()}}))
    expected = expected or cache(name)
    output = parent / (name + ".map"); output.write_bytes(expected)
    package = parent / (name + ".hogpkg")
    manifest = packages.prepare_package(prepared_tags=trees["tags"], prepared_data=trees["data"], original_stock_tags=trees["original"],
        patched_stock_tags=trees["patched"], stock_maps=stock_maps, expected_map=output, scenario=f"levels/test/{name}/{name}",
        toolchain_manifest=producer, destination=package)
    return package, manifest


def install_helpers(directory, helper_binary, outputs):
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    hashes = {}
    for role in ("extract", "build"):
        target = directory / ("invader-" + role + suffix)
        shutil.copyfile(helper_binary, target); target.chmod(0o755)
        hashes[role] = {"source_sha256": sha(target.read_bytes()), "bundled_sha256": sha(target.read_bytes())}
    (directory / "original-pistol").write_bytes(b"whole unchanged pistol")
    (directory / "original-globals").write_bytes(b"original globals")
    for name, data in outputs.items():
        (directory / f"expected-{name}.map").write_bytes(data)
    record = {"schema": 1, "consumer_platform": packages._consumer_platform(), "invader_commit": packages.INVADER_COMMIT,
              "binaries": hashes, "compatible_package_producers": [{"invader_commit": packages.INVADER_COMMIT, "tool_sha256": PINS["binaries"]}]}
    path = directory / "ContentTools.json"; path.write_text(json.dumps(record))
    return path


@unittest.skipUnless(shutil.which("clang"), "clang required for production native consumer fixture")
class NativeCommunityPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix="halo-package-native-build-")
        build = Path(cls.build_temp.name).resolve(); (build / "harness.c").write_text(HARNESS); (build / "helper.c").write_text(HELPER)
        suffix = ".exe" if sys.platform == "win32" else ""
        cls.binary, cls.helper = build / ("consumer" + suffix), build / ("synthetic-helper" + suffix)
        for command in ([shutil.which("clang"), str(SOURCE), str(build / "harness.c"), *native_flags(build), "-o", str(cls.binary)],
                        [shutil.which("clang"), "-std=c11", "-D_GNU_SOURCE", str(build / "helper.c"), "-o", str(cls.helper)]):
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode: raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.build_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="halo-package-native-fixture-"); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.stock = self.root / "stock maps"; self.stock.mkdir()
        for name, kind in zip(packages.STOCK_NAMES, packages.STOCK_TYPES):
            (self.stock / (name + ".map")).write_bytes(cache(name, kind, declared=274734080 if name == "a10" else 4096))
        self.map = cache("authored")
        self.package, self.manifest = create_package(self.root / "producer", self.stock)
        self.tools = self.root / "content tools"; self.record = install_helpers(self.tools, self.helper, {"authored": self.map})
        self.work = self.root / "private work"; self.work.mkdir()
        self.output = self.root / "authored.map"
        self.original_stock = {p.name: p.read_bytes() for p in self.stock.iterdir()}

    def run_consumer(self, package=None, inspect=False, success=True):
        args = [str(self.binary), "inspect" if inspect else "assemble", str(package or self.package)]
        if not inspect: args += [str(self.stock), str(self.tools), str(self.record), str(self.work), str(self.output)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        self.assertEqual(list(self.work.iterdir()), [], "private work must be cleaned on success/failure")
        for name, data in self.original_stock.items():
            path = self.stock / name
            if path.exists() and not path.is_symlink(): self.assertEqual(path.read_bytes(), data)
        return result

    def forge(self, manifest, payload=None, encoded=None):
        raw = self.package.read_bytes(); _, length = packages.HEADER.unpack_from(raw)
        encoded = encoded or json.dumps(manifest).encode()
        payload = raw[16 + length:] if payload is None else payload
        path = self.root / "forged.hogpkg"; path.write_bytes(packages.HEADER.pack(packages.MAGIC, len(encoded)) + encoded + payload)
        return path

    def test_exact_reconstruction_replay_and_originals_preserved(self):
        self.assertIn("result=0", self.run_consumer().stdout)
        self.assertEqual(self.output.read_bytes(), self.map)
        self.assertEqual((self.tools / "invocations.log").read_text().splitlines(), ["extract"] * 3 + ["build"])
        before = (self.tools / "invocations.log").read_bytes()
        self.assertIn("result=1", self.run_consumer().stdout)
        self.assertEqual((self.tools / "invocations.log").read_bytes(), before)

    def test_compressed_exact_reconstruction_inspection_replay_and_cleanup(self):
        compressed = self.root / "authored.mapog"
        compressed.write_bytes(compressed_package(self.package.read_bytes()))
        inspection = self.run_consumer(compressed, inspect=True)
        self.assertIn("id=authored", inspection.stdout)
        self.assertIn(f"package_bytes={compressed.stat().st_size}", inspection.stdout)
        self.assertIn("result=0", self.run_consumer(compressed).stdout)
        self.assertEqual(self.output.read_bytes(), self.map)
        before = (self.tools / "invocations.log").read_bytes()
        self.assertIn("result=1", self.run_consumer(compressed).stdout)
        self.assertEqual((self.tools / "invocations.log").read_bytes(), before)
        compressed.write_bytes(compressed.read_bytes() + b"trailing")
        self.run_consumer(compressed, success=False)
        self.assertEqual(self.output.read_bytes(), self.map)

    def test_compressed_valid_outer_cannot_bypass_inner_literal_hashes(self):
        raw = bytearray(self.package.read_bytes()); raw[-1] ^= 1
        compressed = self.root / "forged.mapog"; compressed.write_bytes(compressed_package(raw))
        self.run_consumer(compressed, inspect=True, success=False)
        self.run_consumer(compressed, success=False)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.tools / "invocations.log").exists())

    def test_existing_different_map_preserved_without_helpers(self):
        self.output.write_bytes(b"user map")
        self.run_consumer(success=False)
        self.assertEqual(self.output.read_bytes(), b"user map")
        self.assertFalse((self.tools / "invocations.log").exists())

    def test_inspection_authenticates_complete_literal_bytes_and_bounds(self):
        self.assertIn("id=authored", self.run_consumer(inspect=True).stdout)
        for mutation in ("hash", "append", "short", "huge-manifest", "magic"):
            raw = bytearray(self.package.read_bytes())
            if mutation == "hash": raw[-1] ^= 1
            elif mutation == "append": raw += b"extra"
            elif mutation == "short": raw = raw[:-1]
            elif mutation == "huge-manifest": struct.pack_into("<Q", raw, 8, 4 * 1024 * 1024 + 1)
            else: raw[0] ^= 1
            path = self.root / "bad.hogpkg"; path.write_bytes(raw)
            self.run_consumer(path, inspect=True, success=False)

    def test_strict_schema_duplicate_escaped_alias_numeric_and_producer_pins(self):
        changes = [("version", True), ("version", 1.0), ("profile", "pal"), ("id", "bloodgulch"), ("id", "CON"),
                   ("invader_commit", "0" * 40), ("unknown", 0), ("payload_bytes", 2**64)]
        for key, value in changes:
            m = copy.deepcopy(self.manifest); m[key] = value
            self.run_consumer(self.forge(m), inspect=True, success=False)
        m = copy.deepcopy(self.manifest); m["tool_sha256"]["build"] = "0" * 64
        self.run_consumer(self.forge(m), inspect=True, success=False)
        encoded = json.dumps(self.manifest).encode().replace(b'"version": 1', b'"version": 1, "\\u0076ersion": 1')
        self.run_consumer(self.forge(self.manifest, encoded=encoded), inspect=True, success=False)

    def test_paths_prefix_case_aliases_and_windows_devices_rejected(self):
        literal = next(i for i, f in enumerate(self.manifest["files"]) if f["tree"] == "tags" and "texture" in f["path"])
        for path in ("../outside", "/absolute", "foo//bar", "a/CON.txt", "a/CON .txt", "a/foo.", "a/foo ", "foo~1/bar", "foo:stream", "foo\\bar"):
            m = copy.deepcopy(self.manifest); m["files"][literal]["path"] = path
            self.run_consumer(self.forge(m), inspect=True, success=False)
        m = copy.deepcopy(self.manifest); m["files"][literal]["path"] = "weapons/Pistol.weapon/child"
        self.run_consumer(self.forge(m), inspect=True, success=False)
        m = copy.deepcopy(self.manifest); m["files"][literal]["path"] = "Weapons/other.bitmap"
        self.run_consumer(self.forge(m), inspect=True, success=False)

    def test_bad_reference_and_override_original_refused_before_build(self):
        for field in ("stock_path", "original_sha256"):
            m = copy.deepcopy(self.manifest)
            item = next(f for f in m["files"] if field in f)
            item[field] = "missing/stock.tag" if field == "stock_path" else "0" * 64
            self.run_consumer(self.forge(m), success=False)
            self.assertFalse(self.output.exists())
        self.assertNotIn("build", (self.tools / "invocations.log").read_text())

    def test_wrong_helper_platform_allowlist_and_helper_hash_refused(self):
        original = self.record.read_bytes()
        for field in ("consumer_platform", "compatible_package_producers", "bundled_sha256"):
            m = json.loads(original)
            if field == "consumer_platform": m[field] = "wrong"
            elif field == "compatible_package_producers": m[field] = []
            else: m["binaries"]["extract"][field] = "0" * 64
            self.record.write_text(json.dumps(m)); self.run_consumer(success=False)
            self.assertFalse((self.tools / "invocations.log").exists())
        self.record.write_bytes(original)

    def test_stock_full_hash_and_region_are_required(self):
        m = copy.deepcopy(self.manifest); m["stock_inputs"][1]["sha256"] = "0" * 64
        self.run_consumer(self.forge(m), success=False)
        self.assertFalse((self.tools / "invocations.log").exists())

    def test_helper_failure_wrong_output_and_output_metadata_cleanup(self):
        for mode in ("fail", "wrong-output"):
            (self.tools / "mode").write_text(mode); self.run_consumer(success=False); self.assertFalse(self.output.exists())
        (self.tools / "mode").unlink()
        self.output.write_bytes(self.map)
        for field in ("declared_bytes", "tag_bytes"):
            m = copy.deepcopy(self.manifest); m["output"][field] += 1
            self.run_consumer(self.forge(m), success=False)
            self.assertEqual(self.output.read_bytes(), self.map)

    def test_symlinks_and_unsafe_extracted_tree_rejected(self):
        if sys.platform == "win32": self.skipTest("Windows runner symlink privileges vary; native reparse checks execute elsewhere")
        alias = self.root / "alias"; alias.symlink_to(self.stock, target_is_directory=True)
        old = self.stock; self.stock = alias; self.run_consumer(success=False); self.stock = old
        package = self.root / "package-link"; package.symlink_to(self.package)
        self.run_consumer(package, inspect=True, success=False)
        (self.tools / "mode").write_text("symlink"); self.run_consumer(success=False)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
