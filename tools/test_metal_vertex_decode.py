"""Production compact GPU input compared with the existing CPU decoder."""
import ctypes as C
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.metal_shader_validate import ROOT, build_library, generated, vertex_programs


@unittest.skipUnless(sys.platform == "darwin", "Compact GPU decoding requires macOS Metal")
class VertexDecodeGpuTests(unittest.TestCase):
    def test_compact_input_bits_under_original_fast_vertex_contract(self):
        with tempfile.TemporaryDirectory(prefix="metal-vertex-decode-") as temporary:
            folder = Path(temporary)
            library = build_library(folder)
            library.nv2a_vertex_shader_to_msl_compact.argtypes = [C.POINTER(C.c_uint32), C.c_ulong, C.c_ulong]
            library.nv2a_vertex_shader_to_msl_compact.restype = C.c_void_p
            shaders = folder / "shaders"
            shaders.mkdir()
            render = shaders / "render"
            render.mkdir()
            for index, count, words in vertex_programs():
                for mask in (0, 0xFFFF):
                    source = generated(library.nv2a_vertex_shader_to_msl_compact, words, count, mask)
                    self.assertIsNotNone(source)
                    (shaders / f"vertex-{index}-{mask}.metal").write_text(source)
                if index == 37:
                    (render / "expanded.metal").write_text(generated(library.nv2a_vertex_shader_to_msl, words, count, 2))
                    (render / "compact.metal").write_text(generated(library.nv2a_vertex_shader_to_msl_compact, words, count, 2))
            cpu = folder / "cpu.o"
            build = subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-DHALO_MACOS_NATIVE_METAL=1", "-c", str(ROOT / "port/linux/src/metal_vertex_fetch.c"), "-o", str(cpu)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            binary = folder / "decode"
            build = subprocess.run(["clang++", "-std=c++17", "-fobjc-arc", "-O2", "-Wall", "-Wextra", "-Werror",
                "-DHALO_MACOS_NATIVE_METAL=1", str(ROOT / "port/macos/tests/metal_vertex_decode.mm"), str(cpu),
                str(ROOT / "port/macos/host/metal_draw_encoder.mm"),
                "-framework", "Foundation", "-framework", "Metal", "-o", str(binary)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            environment = os.environ.copy()
            environment["MTL_DEBUG_LAYER"] = "1"
            run = subprocess.run([str(binary), str(shaders)], env=environment,
                capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("Metal API Validation Enabled", run.stderr)
            self.assertNotIn("Validation Error", run.stderr)
            proof = json.loads(run.stdout)
            self.assertEqual(proof["formats"], 20)
            self.assertEqual(proof["compact_programs_compiled"], 134)
            self.assertEqual(proof["original_nv2a_render_equal_bytes"], 65536)
            self.assertGreater(proof["exact_register_comparisons"], 33000000)
            print(json.dumps(proof))


if __name__ == "__main__":
    unittest.main()
