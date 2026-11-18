"""Exercise desktop flare ownership and the GL count/generation pair without game assets."""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.test_metal_backbuffer_history import function

ROOT = Path(__file__).resolve().parents[1]
LIGHTS = ROOT / "source/rasterizer/rasterizer_lights.c"
GL = ROOT / "port/linux/src/d3d8_gl.c"
HEADER = ROOT / "port/linux/include/halo_flare_visibility.h"


def declaration(source, name):
    return re.search(r"^struct " + name + r"\s*\{[^}]*\};", source, re.M).group()


def enum(source, member):
    return re.search(r"\benum\s*\{[^{}]*?\b" + member + r"\b[^{}]*\};", source).group()


class DesktopFlareTests(unittest.TestCase):
    def test_only_windows_and_linux_desktop_compile_the_generation_contract(self):
        port = "-DHALO_PORT_MAXIMUM_NETWORK_PLAYERS=128"
        cases = (("Linux", [port, "-D__linux__"], True),
                 ("Windows", [port, "-D_WIN32"], True),
                 ("Xbox", ["-D_WIN32"], False),
                 ("Android", [port, "-D__linux__", "-DHALO_ANDROID"], False),
                 ("Apple guest", [port, "-D__linux__", "-DHALO_ANDROID", "-DHALO_MACOS"], False),
                 ("Metal", [port, "-D__linux__", "-DHALO_MACOS_NATIVE_METAL"], False))
        for target, defines, enabled in cases:
            with self.subTest(target=target):
                preprocessed = subprocess.check_output(["clang", "-undef", "-E", "-P", "-x", "c",
                                                       *defines, str(HEADER)], text=True)
                self.assertEqual("xgpu_visibility_tests_ended" in preprocessed, enabled)

    def run_fixture(self, name, files, cases):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for filename, contents in files.items():
                (folder / filename).write_text(contents)
            windows = sys.platform == "win32"
            probe = folder / (name + ".exe" if windows else name)
            sanitize = [] if windows else ["-fsanitize=address,undefined"]
            math_library = [] if windows else ["-lm"]
            subprocess.run(["clang", "-std=c11", "-O1", "-g", "-Wall", "-Werror",
                            *sanitize, "-DHALO_DESKTOP_GL_FLARE_QUERIES=1",
                            "-I", str(folder), str(ROOT / f"tools/{name}.c"), *math_library, "-o", str(probe)],
                           check=True)
            for case in cases:
                with self.subTest(case=case):
                    subprocess.run([str(probe), case], check=True, timeout=10)

    def test_reordered_reused_and_delayed_flare_slots(self):
        source = LIGHTS.read_text()
        capacity = enum(HEADER.read_text(), "LENS_FLARE_OCCLUSION_SLOT_COUNT")
        config = [capacity, enum(source, "_lens_flare_first_person_weapon_flag"),
                  enum(source, "_lens_flare_dynamic_light_flag"), enum(source, "LENS_FLARE_OCCLUSION_SLOT_PROBES")]
        config += [declaration(source, name) for name in ("lens_flare_occlusion_test_results",
                   "rasterizer_lens_flare_submit_parameters", "lens_flare_occlusion_slot")]
        implementations = source.split("/* ---------- private code */", 1)[1]
        names = ("lens_flare_parameters_get", "lens_flare_occlusion_test_results_get",
                 "lens_flare_occlusion_test_index", "lens_flare_occlusion_visible_pixels",
                 "rasterizer_lights_begin_for_new_frame", "rasterizer_lights_reset_for_new_map")
        code = "\n".join(function(implementations, name) for name in names)
        self.run_fixture("desktop_flare_occlusion", {"config.inc": "\n".join(config), "under_test.inc": code},
                         ("own-counts", "stable-slots", "reused-late", "reused-dropped", "no-slot",
                          "split-screen", "new-map", "occlusion-off"))

    def test_desktop_query_buffer_ownership_and_synchronous_fallback(self):
        source = GL.read_text()
        config = "\n".join((enum(HEADER.read_text(), "LENS_FLARE_OCCLUSION_SLOT_COUNT"),
                            enum(source, "FLARE_BATCH_COUNT"), declaration(source, "flare_query_record"),
                            declaration(source, "flare_query_batch")))
        adapter = source.split("/* ---------- visibility (occlusion) tests */", 1)[1]
        adapter = adapter.split("/* ---------- render and texture stage state */", 1)[0]
        self.run_fixture("desktop_flare_queries", {"config.inc": config, "under_test.inc": adapter},
                         ("buffer", "direct"))
