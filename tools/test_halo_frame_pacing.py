#!/usr/bin/env python3
"""CPU fake-clock tests for native render pacing and real config registration.

The optional --ilp32 mode executes the same C cases through an existing CPU
guest executor. It never creates a graphics context, sleeps or launches Halo.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/linux/src/halo_frame_pacing.c"
HEADER = SOURCE.with_suffix(".h")
CASES = (
    "supported_and_malformed_caps",
    "interpolation_off_preserves_original_throttle",
    "two_minute_exact_cadence_with_render_work",
    "cap_change_starts_fresh_period",
    "uncapped_and_reenabled_reset",
    "long_stalls_discard_debt_and_short_lateness_recovers",
    "backwards_clock_starts_fresh_period",
    "uint64_overflow_cannot_wrap_deadline",
    "wake_jitter_does_not_accumulate_drift",
    "null_and_explicit_reset",
    "alternating_30hz_render_work_recovers_60fps",
    "short_oversleep_preserves_absolute_cadence",
    "one_period_lateness_discards_debt",
)

HARNESS = r'''
#include <stddef.h>
#include <stdint.h>
#include <limits.h>
#include <time.h>
#include "halo_frame_pacing.c"
#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)
_Static_assert(sizeof(uint64_t) == 8, "64-bit monotonic nanoseconds");
_Static_assert(sizeof(struct halo_frame_pacing) == 24, "fixed-width CPU state");
_Static_assert(offsetof(struct halo_frame_pacing, fraction) == 20, "ILP32 state layout");
#ifdef HALO_PACING_ILP32
_Static_assert(sizeof(long) == 4 && sizeof(void *) == 4, "actual guest ILP32");
_Static_assert(sizeof(time_t) == 4 && sizeof(struct timespec) == 8, "guest time32 ABI");
_Static_assert(offsetof(struct timespec, tv_nsec) == 4, "guest nanosecond offset");
/* Aggregate zero initialization may lower to memset in this freestanding
 * fixture. Volatile stores prevent its implementation becoming recursive. */
void *memset(void *destination, int value, size_t count) {
    volatile unsigned char *bytes = (volatile unsigned char *)destination;
    for (size_t i = 0; i < count; i++) bytes[i] = (unsigned char)value;
    return destination;
}
#endif
static uint64_t ceil_period(unsigned cap) {
    return (UINT64_C(1000000000) + cap - 1) / cap;
}
static int clean(const struct halo_frame_pacing *p) {
    return !p->deadline_ns && !p->previous_now_ns && !p->frame_limit && !p->fraction;
}
int halo_pacing_test(unsigned test) {
    struct halo_frame_pacing p = {0};
    const unsigned caps[] = {30, 60, 120};
    const uint64_t base = UINT64_C(4294967000);
    uint64_t deadline, now;
    unsigned i, frame;
    switch (test) {
    case 0: {
        const long invalid[] = {0, -1, 1, 29, 31, 59, 61, 119, 121, LONG_MIN, LONG_MAX};
        for (i = 0; i < 3; i++) {
            halo_frame_pacing_reset(&p);
            CHECK(halo_frame_pacing_deadline(&p, base, caps[i], 1) == base + ceil_period(caps[i]));
        }
        for (i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
            (void)halo_frame_pacing_deadline(&p, base, 60, 1);
            CHECK(!halo_frame_pacing_deadline(&p, base + 1, invalid[i], 1));
            CHECK(clean(&p));
        }
        break;
    }
    case 1:
        for (i = 0; i < 3; i++) {
            (void)halo_frame_pacing_deadline(&p, base, caps[i], 1);
            CHECK(!halo_frame_pacing_deadline(&p, base + 1, caps[i], 0));
            CHECK(clean(&p));
            CHECK(halo_frame_pacing_deadline(&p, base + 2, caps[i], 1) == base + 2 + ceil_period(caps[i]));
        }
        break;
    case 2:
        for (i = 0; i < 3; i++) {
            unsigned cap = caps[i];
            halo_frame_pacing_reset(&p);
            now = base;
            for (frame = 0; frame < cap * 120; frame++) {
                /* Independent cumulative-period oracle, with a fake clock
                 * advanced through sleep plus varying next-frame work. */
                uint64_t expected = base + ((uint64_t)(frame + 1) * UINT64_C(1000000000) + cap - 1) / cap;
                deadline = halo_frame_pacing_deadline(&p, now, cap, 1);
                CHECK(deadline == expected && deadline > now);
                now = deadline + (frame % 7) * UINT64_C(100000);
            }
            CHECK(p.deadline_ns == base + UINT64_C(120000000000));
        }
        break;
    case 3:
        now = halo_frame_pacing_deadline(&p, base, 30, 1) + 2000;
        CHECK(halo_frame_pacing_deadline(&p, now, 120, 1) == now + ceil_period(120));
        now = p.deadline_ns + 1000;
        CHECK(halo_frame_pacing_deadline(&p, now, 60, 1) == now + ceil_period(60));
        break;
    case 4:
        (void)halo_frame_pacing_deadline(&p, base, 60, 1);
        CHECK(!halo_frame_pacing_deadline(&p, base + 1000, 0, 1) && clean(&p));
        CHECK(halo_frame_pacing_deadline(&p, base + 100000, 60, 1) == base + 100000 + ceil_period(60));
        break;
    case 5: {
        uint64_t restarted;
        deadline = halo_frame_pacing_deadline(&p, base, 120, 1);
        now = deadline + UINT64_C(10000000000);
        CHECK(!halo_frame_pacing_deadline(&p, now, 120, 1));
        CHECK(p.deadline_ns == now);
        restarted = now;
        CHECK(halo_frame_pacing_deadline(&p, now + 1000, 120, 1) == now + ceil_period(120));
        now = p.deadline_ns + ceil_period(120) + 1;
        CHECK(!halo_frame_pacing_deadline(&p, now, 120, 1));
        CHECK(p.deadline_ns == restarted + (UINT64_C(2000000000) + 119) / 120);
        CHECK(halo_frame_pacing_deadline(&p, now + 1000, 120, 1) ==
            restarted + (UINT64_C(3000000000) + 119) / 120);
        /* Continuously slower rendering never adds an extra period. */
        for (frame = 0; frame < 1000; frame++) {
            now += UINT64_C(100000000);
            CHECK(!halo_frame_pacing_deadline(&p, now, 120, 1));
        }
        break;
    }
    case 6:
        (void)halo_frame_pacing_deadline(&p, base, 60, 1);
        CHECK(halo_frame_pacing_deadline(&p, base - 100, 60, 1) == base - 100 + ceil_period(60));
        break;
    case 7:
        CHECK(!halo_frame_pacing_deadline(&p, UINT64_MAX - 1, 30, 1));
        CHECK(clean(&p));
        CHECK(halo_frame_pacing_deadline(&p, 1, 30, 1) == 1 + ceil_period(30));
        break;
    case 8:
        now = base;
        for (frame = 0; frame < 7200; frame++) {
            uint64_t expected = base + ((uint64_t)(frame + 1) * UINT64_C(1000000000) + 119) / 120;
            deadline = halo_frame_pacing_deadline(&p, now, 120, 1);
            CHECK(deadline == expected);
            /* Fake wakeup overshoot plus CPU/GPU work, below one period. */
            now = deadline + UINT64_C(1000000) + (frame % 5) * UINT64_C(250000);
        }
        CHECK(p.deadline_ns == base + UINT64_C(60000000000));
        break;
    case 9:
        CHECK(!halo_frame_pacing_deadline(NULL, base, 60, 1));
        halo_frame_pacing_reset(NULL);
        (void)halo_frame_pacing_deadline(&p, base, 60, 1);
        halo_frame_pacing_reset(&p);
        CHECK(clean(&p));
        break;
    case 10: {
        unsigned missed = 0, waited = 0;
        now = halo_frame_pacing_deadline(&p, base, 60, 1);
        for (frame = 0; frame < 7200; frame++) {
            uint64_t expected = base + ((uint64_t)(frame + 2) * UINT64_C(1000000000) + 59) / 60;
            /* Simulation work arrives at 30 Hz: a 22 ms frame followed by a 7 ms
             * interpolation frame. The 29 ms pair fits within two 60 Hz slots. */
            now += (frame & 1) ? UINT64_C(7000000) : UINT64_C(22000000);
            deadline = halo_frame_pacing_deadline(&p, now, 60, 1);
            CHECK(p.deadline_ns == expected);
            if (frame & 1) {
                CHECK(deadline == expected && deadline > now);
                now = deadline;
                waited++;
            } else {
                CHECK(!deadline && now > expected && now - expected < ceil_period(60));
                missed++;
            }
        }
        CHECK(missed == 3600 && waited == 3600);
        CHECK(now == base + (UINT64_C(7201000000000) + 59) / 60);
        break;
    }
    case 11: {
        unsigned missed = 0;
        now = base;
        for (frame = 0; frame < 7200; frame++) {
            uint64_t expected = base + ((uint64_t)(frame + 1) * UINT64_C(1000000000) + 119) / 120;
            deadline = halo_frame_pacing_deadline(&p, now, 120, 1);
            CHECK(p.deadline_ns == expected);
            if (now >= expected) {
                CHECK(!deadline);
                missed++;
            } else {
                CHECK(deadline == expected);
                now = deadline;
            }
            /* Occasionally oversleep beyond the next slot by 1.25 ms. A
             * subsequent 1 ms frame must restore the original phase. */
            now += frame % 17 == 0 ? ceil_period(120) + UINT64_C(1250000) : UINT64_C(1000000);
        }
        CHECK(missed > 0);
        CHECK(p.deadline_ns == base + UINT64_C(60000000000));
        break;
    }
    case 12:
        for (i = 0; i < 3; i++) {
            unsigned cap = caps[i];
            uint64_t first = base + ceil_period(cap);
            uint64_t second = base + (UINT64_C(2000000000) + cap - 1) / cap;
            uint64_t third = base + (UINT64_C(3000000000) + cap - 1) / cap;
            uint64_t second_period = second - first;
            halo_frame_pacing_reset(&p);
            CHECK(halo_frame_pacing_deadline(&p, base, cap, 1) == first);
            CHECK(!halo_frame_pacing_deadline(&p, second, cap, 1));
            CHECK(p.deadline_ns == second);
            CHECK(halo_frame_pacing_deadline(&p, second, cap, 1) == third);
            halo_frame_pacing_reset(&p);
            CHECK(halo_frame_pacing_deadline(&p, base, cap, 1) == first);
            now = second + second_period - 1;
            CHECK(!halo_frame_pacing_deadline(&p, now, cap, 1));
            CHECK(p.deadline_ns == second);
            deadline = halo_frame_pacing_deadline(&p, now, cap, 1);
            CHECK(p.deadline_ns == third);
            /* The following fractional period can be 1 ns shorter, placing
             * this exact-boundary fake clock directly on its deadline. */
            CHECK(deadline == (third > now ? third : 0));
            halo_frame_pacing_reset(&p);
            CHECK(halo_frame_pacing_deadline(&p, base, cap, 1) == first);
            now = second + second_period;
            CHECK(!halo_frame_pacing_deadline(&p, now, cap, 1));
            CHECK(p.deadline_ns == now);
            CHECK(halo_frame_pacing_deadline(&p, now + 1000, cap, 1) == now + ceil_period(cap));
        }
        break;
    default: return -1;
    }
    return 0;
}
unsigned guest_test(unsigned unused) {
    (void)unused;
    for (unsigned i = 0; i < 13; i++) {
        int status = halo_pacing_test(i);
        if (status) return 1000 * (i + 1) + (unsigned)status;
    }
    return 0;
}
'''

CONFIG_PREFIX = r'''
#define __HALO_LINUX_PLATFORM_H
typedef int BOOL;
#define TRUE 1
#define FALSE 0
void platform_log(const char *, ...);
'''
CONFIG_PROBE = r'''
#include "port_config.c"
void platform_log(const char *format, ...) { (void)format; }
int main(void) {
    unsigned found = 0;
    for (unsigned i = 0; i < NUMBER_OF_CONFIG_SETTINGS; i++) {
        const struct config_setting *s = &config_settings[i];
        if (strcmp(s->name, "display.frame_limit") && strcmp(s->name, "display.render_height")) continue;
        if (s->type != _config_integer || s->environment || s->platforms != _platform_all) return 1;
        if (strcmp(s->default_value, !strcmp(s->name, "display.frame_limit") ? "0" : "480")) return 2;
        found++;
    }
    printf("%u %ld %ld\n", found, config_integer("display.frame_limit"), config_integer("display.render_height"));
    return 0;
}
'''


def run(*args):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


class FramePacingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("clang"):
            raise unittest.SkipTest("clang required")
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-frame-pacing-")
        cls.folder = Path(cls.temp.name)
        source = cls.folder / "probe.c"
        source.write_text(HARNESS)
        library = cls.folder / "pacing.dylib"
        run("clang", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
            "-I", SOURCE.parent, source, "-o", library)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.halo_pacing_test.argtypes = [ctypes.c_uint]
        cls.lib.halo_pacing_test.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()


for _index, _name in enumerate(CASES):
    def _test(self, index=_index):
        self.assertEqual(self.lib.halo_pacing_test(index), 0, "C fixture line failed")
    setattr(FramePacingTests, "test_" + _name, _test)


class NativeConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-native-display-config-")
        cls.folder = Path(cls.temp.name)
        (cls.folder / "prefix.h").write_text(CONFIG_PREFIX)
        probe = cls.folder / "config.c"
        probe.write_text(CONFIG_PROBE)
        sdl = Path(os.environ.get("HALO_MACOS_SDL_PREFIX", "/opt/homebrew/opt/sdl3"))
        if not (sdl / "include/SDL3/SDL.h").exists():
            cls.temp.cleanup()
            raise unittest.SkipTest("SDL3 headers required for production config parser")
        cls.executables = {}
        for name, defines in (("native", ["HALO_MACOS=1", "HALO_MACOS_NATIVE_METAL=1"]),
                              ("angle", ["HALO_MACOS=1"]), ("disabled", ["HALO_MACOS=1", "HALO_MACOS_NATIVE_METAL=0"]),
                              ("android", [])):
            executable = cls.folder / name
            run("clang", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                "-DHALO_ANDROID=1", *("-D" + define for define in defines), "-include", cls.folder / "prefix.h",
                "-I", SOURCE.parent, "-I", sdl / "include", "-I", ROOT / "port/third_party/tomlc17",
                probe, ROOT / "port/third_party/tomlc17/tomlc17.c", "-o", executable)
            cls.executables[name] = executable

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def config(self, target, content=None):
        with tempfile.TemporaryDirectory(dir=self.folder) as name:
            folder = Path(name)
            path = folder / "config.toml"
            if content is not None:
                path.write_text(content)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
            environment.update(HALO_SAVE_ROOT=name, HALO_DATA_ROOT=name)
            result = subprocess.run([str(self.executables[target])], env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return tuple(map(int, result.stdout.split())), path.read_text()

    def test_native_defaults_registered_as_integer_config_only(self):
        values, text = self.config("native")
        self.assertEqual(values, (2, 0, 480))
        self.assertIn("frame_limit = 0", text)
        self.assertIn("render_height = 480", text)

    def test_other_renderers_do_not_register_or_write_native_options(self):
        for target in ("angle", "disabled", "android"):
            with self.subTest(target=target):
                values, text = self.config(target)
                self.assertEqual(values, (0, 0, 0))
                self.assertNotIn("frame_limit", text)
                self.assertNotIn("render_height", text)

    def test_existing_values_and_unrelated_text_preserved(self):
        content = '# player comment\n[display]\nframe_limit = 120 # cap\nrender_height = 1080\ncustom = "keep"\n'
        values, text = self.config("native", content)
        self.assertEqual(values, (2, 120, 1080))
        self.assertIn(content, text)

    def test_wrong_toml_types_use_defaults(self):
        content = '[display]\nframe_limit = "120"\nrender_height = true\n'
        values, text = self.config("native", content)
        self.assertEqual(values, (2, 0, 480))
        self.assertIn(content, text)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ilp32(args):
    """Build and execute these same clock-free cases using the actual guest ABI."""
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    from tools.android_build import GUEST_ABI_FLAGS
    snapshot = output / "source"
    snapshot.mkdir()
    for source in (SOURCE, HEADER, Path(__file__).resolve()):
        shutil.copy2(source, snapshot / source.name)
    probe = snapshot / "probe.c"
    probe.write_text(HARNESS)
    llvm, plugin, executor = args.llvm.resolve(), args.plugin.resolve(), args.executor.resolve()
    linker = args.linker.absolute()  # Preserve ld.lld's driver-selecting basename.
    source_hashes = {str(path): sha(path) for path in (SOURCE, HEADER, Path(__file__).resolve())}
    resource = Path(run(llvm / "clang", "-print-resource-dir").stdout.strip())
    run(llvm / "clang", *GUEST_ABI_FLAGS, "-DHALO_PACING_ILP32=1", "-D_XOPEN_SOURCE=700",
        "-std=c11", "-ffreestanding", "-fno-builtin", "-Wall", "-Wextra", "-Werror",
        "-isystem", resource / "include", "-I", ROOT / "build/macos-metal/guest/libc_include",
        "-I", ROOT / "port/android/guest/libc/arch/arm64_32",
        "-I", ROOT / "build/android/third_party/musl-1.2.5/arch/generic",
        "-I", ROOT / "build/android/third_party/musl-1.2.5/include", "-I", snapshot,
        "-emit-llvm", "-S", probe, "-o", output / "guest.ll")
    run(llvm / "opt", "-load-pass-plugin=" + str(plugin), "-passes=halo-rebase,verify",
        "-S", output / "guest.ll", "-o", output / "guest.rebased.ll")
    run(llvm / "llc", "-O2", "-mtriple=arm64_32-apple-watchos", "-aarch64-neon-syntax=generic",
        output / "guest.rebased.ll", "-o", output / "guest.darwin.s")
    run(sys.executable, ROOT / "tools/android_asm_convert.py", output / "guest.darwin.s", output / "guest.s")
    # The retained executor expects these four imports. The CPU fixture has
    # no calls to any of them and never initializes Metal.
    imports = output / "unused-imports.list"
    shutil.copy2(ROOT / "port/macos/metal_imports.list", imports)
    run(sys.executable, ROOT / "tools/android_imports.py", output / "imports.s", imports)
    for name in ("guest", "imports"):
        run(llvm / "clang", "--target=aarch64-linux-android", "-c", output / (name + ".s"), "-o", output / (name + ".o"))
    script = output / "guest.ld"
    script.write_text("ENTRY(guest_test)\nSECTIONS { . = 0x88000000; .text : { *(.text*) } . = ALIGN(16384); .rodata : { *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) *(COMMON) } }\n")
    run(linker, "-m", "aarch64elf", "-T", script, output / "guest.o", output / "imports.o", "-o", output / "guest.elf")
    symbols = {}
    for line in run(llvm / "llvm-nm", "--defined-only", output / "guest.elf").stdout.splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    copied = output / "host_ilp32_probe"
    shutil.copy2(executor, copied)
    command = [str(copied), str(output / "guest.elf"), *(hex(symbols[name]) for name in
               ("__host_import_table", "__host_import_names", "__host_import_count")), "0x800000"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (output / "stdout.json").write_text(result.stdout)
    (output / "stderr.log").write_text(result.stderr)
    observed = json.loads(result.stdout)
    passed = result.returncode == 0 and observed.get("passed") is True and observed.get("guest_result") == 0 and observed.get("guest_pointer_bits") == 32
    proof = dict(schema_version=1, kind="render_frame_pacing_ilp32_cpu", passed=passed, cases=CASES,
                 observed=observed, execution_command=command, source_sha256=source_hashes,
                 input_sha256={str(path): sha(path) for path in output.rglob("*") if path.is_file()},
                 toolchain_sha256={str(path): sha(path) for path in (plugin, llvm / "clang", llvm / "opt", llvm / "llc", linker)},
                 limits=["CPU fake clocks only; no actual sleep, renderer, GPU, simulation or achieved-FPS measurement."])
    if source_hashes != {str(path): sha(path) for path in (SOURCE, HEADER, Path(__file__).resolve())}:
        raise RuntimeError("Source changed during proof")
    (output / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(dict(passed=passed, cases=len(CASES), result=str(output / "result.json"))))
    if not passed:
        raise RuntimeError(result.stdout + result.stderr)


if __name__ == "__main__":
    if "--ilp32" in sys.argv:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--ilp32", action="store_true")
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--plugin", type=Path, required=True)
        parser.add_argument("--executor", type=Path, required=True)
        parser.add_argument("--llvm", type=Path, default=Path("/opt/homebrew/opt/llvm@22/bin"))
        parser.add_argument("--linker", type=Path, default=Path("/opt/homebrew/opt/lld@22/bin/ld.lld"))
        ilp32(parser.parse_args())
    else:
        unittest.main()
