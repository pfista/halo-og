"""Build-graph guards: native Metal must not acquire an ANGLE dependency."""
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import android_build, macos_build, ninja_syntax
from tools.macos_metal_imports import native_imports


class RendererBuildTests(unittest.TestCase):
    def graph(self, renderer):
        stream = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="halo-guest-build-graph-") as directory:
            tools = Path(directory)
            for name in ("llvm-ar", "ld.lld", "GLES3/gl32.h", "GLES2/gl2ext.h", "KHR/khrplatform.h"):
                path = tools / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            settings = SimpleNamespace(macos=True, ios=False, macos_renderer=renderer,
                                       android_guest_only=True, android_guest_llvm_bin=tools,
                                       android_guest_gl_include=tools if renderer == "angle" else None,
                                       android_guest_cc="tools/macos_guest_cc.py", port_pgo="off")
            with patch.object(android_build, "fetch_third_party"):
                android_build.generate_android_build(ninja_syntax.Writer(stream), settings)
        return stream.getvalue()

    def test_native_guest_omits_every_gl_bridge(self):
        graph = self.graph("metal")
        for absent in ("d3d8_gl.c", "gl_functions.c", "guest_gl.c", "gl_imports.list",
                       "gl_include", "GLES2", "GLES3", "android_gl_stubs"):
            self.assertNotIn(absent, graph)
        for required in ("d3d8_metal.c", "HALO_MACOS_NATIVE_METAL=1", "build/macos-metal/halo_guest.elf",
                         "native_host_imports.list", "metal_imports.list", "--renderer metal --plugin-only"):
            self.assertIn(required, graph)

    def test_default_guest_keeps_angle_and_old_output(self):
        graph = self.graph("angle")
        for required in ("d3d8_gl.c", "gl_functions.c", "guest_gl.c", "gl_imports.list",
                         "build/macos/halo_guest.elf"):
            self.assertIn(required, graph)
        self.assertNotIn("d3d8_metal.c", graph)
        self.assertNotIn("HALO_MACOS_NATIVE_METAL", graph)
        self.assertNotIn("build/macos-metal", graph)

    def test_filter_retains_input_audio_events_and_native_wire(self):
        original = Path("port/android/host_imports.list").read_text()
        filtered = native_imports(original)
        names = {line for line in filtered.splitlines() if line and not line.startswith("#")}
        self.assertFalse(any(name.startswith(("hostgl_", "host_gl_", "host_sdl_gl_")) for name in names))
        for name in ("host_sdl_create_window", "host_sdl_poll_event", "host_sdl_open_audio_stream",
                     "host_sdl_open_gamepad", "host_syscall"):
            self.assertIn(name, names)
        self.assertEqual(native_imports(filtered), filtered)

    def host_commands(self, renderer):
        commands = []
        with tempfile.TemporaryDirectory(prefix="halo-host-build-graph-") as directory:
            root = Path(directory)
            for name in ("EGL", "GLESv2"):
                (root / f"angle/{name}.xcframework/macos-arm64/lib{name}.framework").mkdir(parents=True)
            with patch.object(macos_build, "RENDERER", renderer), patch.object(macos_build, "BUILD", root / "output"), \
                    patch.object(macos_build, "ANGLE", root / "angle"), \
                    patch.object(macos_build, "setup_sparkle", return_value=root / "Sparkle.framework"), \
                    patch.object(macos_build, "require", side_effect=lambda path: path), \
                    patch.object(macos_build, "run", side_effect=lambda *args: commands.append([str(arg) for arg in args])):
                macos_build.build_host()
        return commands

    def test_native_host_excludes_gl_sources_headers_libraries(self):
        commands = self.host_commands("metal")
        text = "\n".join(" ".join(command) for command in commands)
        for absent in ("host_gl.c", "host_gl_bridge.c", "host_perf.c", "libEGL", "libGLESv2", "toolchain/gl"):
            self.assertNotIn(absent, text)
        for required in ("host_sdl.c", "host_metal.mm", "metal_draw_encoder.mm", "HALO_MACOS_NATIVE_METAL=1",
                         "-lSDL3", "-framework Metal", "-framework Cocoa"):
            self.assertIn(required, text)

    def test_default_host_keeps_gl_sources_and_libraries(self):
        commands = self.host_commands("angle")
        text = "\n".join(" ".join(command) for command in commands)
        for required in ("host_gl.c", "host_gl_bridge.c", "host_perf.c", "libEGL", "libGLESv2", "toolchain/gl"):
            self.assertIn(required, text)
        self.assertNotIn("HALO_MACOS_NATIVE_METAL", text)


if __name__ == "__main__":
    unittest.main()
