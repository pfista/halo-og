"""Exercise the real host's TOML editor and pre-SDL renderer dispatch on the CPU."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "port/macos/host/host_renderer.c"
TOML = ROOT / "port/third_party/tomlc17/tomlc17.c"


class RendererSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which("clang")
        if not cls.compiler:
            raise unittest.SkipTest("clang is required for the actual host helper")
        cls.build = tempfile.TemporaryDirectory(prefix="halo-renderer-helper-")
        directory = Path(cls.build.name)
        cls.libraries = []
        for native in (False, True):
            output = directory / ("metal.dylib" if native else "angle.dylib")
            command = [cls.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
                       "-D_DARWIN_C_SOURCE", "-dynamiclib", str(HELPER), str(TOML), "-o", str(output)]
            if native:
                command.append("-DHALO_MACOS_NATIVE_METAL=1")
            subprocess.run(command, check=True, capture_output=True, text=True)
            library = ctypes.CDLL(str(output))
            library.host_renderer_read.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
            library.host_renderer_write.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
            library.host_renderer_set_paths.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            library.host_renderer_default_guest.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            cls.libraries.append(library)
        driver = directory / "driver.c"
        driver.write_text('''#include "host_renderer.h"
#include <stdio.h>
int main(int argc, char **argv) {
    if (argc < 4) return 99;
    host_renderer_set_paths(argv[1], argv[2]);
    char note[256] = "";
    host_renderer_dispatch_native(argc - 3, argv + 3, note, sizeof(note));
    printf("fallback:%s\\n", note);
    return 0;
}
''')
        cls.driver = directory / "driver"
        subprocess.run([cls.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
                        "-D_DARWIN_C_SOURCE", "-I", str(HELPER.parent),
                        str(driver), str(HELPER), str(TOML), "-o", str(cls.driver)],
                       check=True, capture_output=True, text=True)
        child = directory / "child.c"
        child.write_text('''#include <stdio.h>
int main(int argc, char **argv) {
    printf("native:%d\\n", argc);
    for (int index = 0; index < argc; index++) printf("arg:%s\\n", argv[index]);
    return 17;
}
''')
        cls.child = directory / "child"
        subprocess.run([cls.compiler, "-std=c17", "-Wall", "-Wextra", "-Werror",
                        str(child), "-o", str(cls.child)], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="halo-renderer-settings-")
        self.directory = Path(self.temporary.name)
        self.config = self.directory / "config.toml"
        self.library = self.libraries[0]

    def tearDown(self):
        self.temporary.cleanup()

    def read(self, library=None):
        error = ctypes.create_string_buffer(256)
        result = (library or self.library).host_renderer_read(os.fsencode(self.directory), error, len(error))
        return result, error.value.decode()

    def write(self, renderer=1):
        error = ctypes.create_string_buffer(256)
        result = self.library.host_renderer_write(os.fsencode(self.directory), renderer, error, len(error))
        return result, error.value.decode()

    def test_missing_and_unset_use_metal_and_preserve_explicit_angle(self):
        self.assertEqual(self.read(), (1, ""))
        self.assertEqual(self.write(), (1, ""))
        self.assertEqual(self.config.read_text(), '[display]\nrenderer = "metal"\n')
        self.assertEqual(self.read(), (1, ""))
        self.assertEqual(self.library.host_renderer_active(), 0)  # Selection cannot change this process.
        for source in ('', '[display]\nvsync = true\n', '[network]\naddress = "local"\n'):
            with self.subTest(source=source):
                self.config.write_text(source)
                for library in self.libraries:
                    self.assertEqual(self.read(library), (1, ""))
                self.assertEqual(self.config.read_text(), source)
        self.assertEqual(self.write(0), (1, ""))
        for library in self.libraries:
            self.assertEqual(self.read(library), (0, ""))

    def test_typed_invalid_and_unknown_choices_fall_back_without_repair(self):
        for source in ('[display]\nrenderer = 1\n', '[display]\nrenderer = true\n',
                       '[display]\nrenderer = "future"\n', '[display]\nrenderer = "ANGLE"\n',
                       'display = 1\n', '[[display]]\nrenderer = "metal"\n',
                       '[display\nrenderer = "metal"\n'):
            with self.subTest(source=source):
                self.config.write_text(source)
                choice, error = self.read()
                self.assertEqual(choice, 0)
                self.assertTrue(error)
                self.assertEqual(self.config.read_text(), source)

    def test_value_replacement_preserves_comments_other_tables_and_fresh_external_edits(self):
        source = '# header\r\n[display] # retain\r\nrenderer = "angle" # engine\r\nvsync = false\r\n' \
                 '[network]\r\naddress = "local"\r\n'
        self.config.write_bytes(source.encode())
        self.assertEqual(self.write(), (1, ""))
        expected = source.replace('"angle"', '"metal"')
        self.assertEqual(self.config.read_bytes(), expected.encode())
        expected = expected.replace('vsync = false', 'vsync = true') + '# guest saved later\r\n'
        self.config.write_bytes(expected.encode())
        self.assertEqual(self.write(0), (1, ""))
        self.assertEqual(self.config.read_bytes(), expected.replace('"metal"', '"angle"').encode())

    def test_parsed_string_coordinates_cover_quoted_and_dotted_keys(self):
        for source in ('["display"]\n"renderer" = "angle" # retain\n',
                       "'display'.'renderer' = 'angle'\n",
                       'display = { "renderer" = "angle", vsync = true }\n'):
            with self.subTest(source=source):
                self.config.write_text(source)
                self.assertEqual(self.write(), (1, ""))
                self.assertEqual(self.read(), (1, ""))
                self.assertEqual(self.config.read_text(), source.replace('"angle"', '"metal"').replace("'angle'", '"metal"'))

    def test_all_toml_string_forms_replace_only_the_renderer_token(self):
        for token in ('"an\\u0067le"', "'angle'", '"""angle"""', "'''angle'''",
                      '"""\nangle"""', "'''\nangle'''", '"""future""""', "'''future'''''",
                      '"escaped\\\"quote"', '"""one\\\"two\nthree"""', '""', "''",
                      '""""""', "''''''", '"""\n\n"""', "'''\r\nangle'''",
                      '"""\r\nangle"""'):
            with self.subTest(token=token):
                source = f'[display]\nrenderer = {token} # retain\nvsync = false\n'
                self.config.write_text(source)
                self.assertEqual(self.write(), (1, ""))
                self.assertEqual(self.config.read_text(), '[display]\nrenderer = "metal" # retain\nvsync = false\n')
                self.assertEqual(self.read(), (1, ""))

    def test_absent_key_in_explicit_implicit_dotted_and_inline_tables(self):
        for source in ('[display] # header\nvsync = true\n[network]\nport = 123\n',
                       '[display]', '[display.sub]\nvalue = 4\n', 'display.vsync = true\n',
                       'display = {} # keep\n', 'display = { vsync = true } # keep\n',
                       '"display" = { "vsync" = true }\n', '[network]\nport = 123\n'):
            with self.subTest(source=source):
                self.config.write_text(source)
                self.assertEqual(self.write(), (1, ""))
                self.assertEqual(self.read(), (1, ""))
                if 'vsync' in source:
                    self.assertIn('vsync', self.config.read_text())
                if '# keep' in source:
                    self.assertIn('# keep', self.config.read_text())

    def test_wrong_types_and_malformed_files_fail_without_replacement(self):
        for source in ('[display]\nrenderer = true\n', 'display = 3\n',
                       '[[display]]\nrenderer = "angle"\n', '[display]\nrenderer = [1]\n', '[broken'):
            with self.subTest(source=source):
                self.config.write_text(source)
                result, error = self.write()
                self.assertEqual(result, 0)
                self.assertTrue(error)
                self.assertEqual(self.config.read_text(), source)
        self.config.write_text('[display]\nrenderer = "angle"\n')
        self.assertEqual(self.write(2)[0], 0)
        self.assertEqual(self.read(), (0, ""))

    def test_readonly_symlink_oversized_and_nul_files_are_not_overwritten(self):
        original = b'[display]\nrenderer = "angle"\n'
        self.config.write_bytes(original)
        self.config.chmod(0o444)
        self.assertEqual(self.write()[0], 0)
        self.assertEqual(self.config.read_bytes(), original)
        self.config.chmod(0o600)
        target = self.directory / "external.toml"
        self.config.rename(target)
        self.config.symlink_to(target)
        self.assertTrue(self.read()[1])
        self.assertEqual(self.write()[0], 0)
        self.assertEqual(target.read_bytes(), original)
        self.config.unlink()
        for contents in (b'#' * (1024 * 1024 + 1), original + b'\0'):
            self.config.write_bytes(contents)
            self.assertTrue(self.read()[1])
            self.assertEqual(self.write()[0], 0)
            self.assertEqual(self.config.read_bytes(), contents)
        self.assertFalse(list(self.directory.glob('config.toml.*')))

    def test_atomic_replacement_retains_permissions_and_leaves_no_temp_files(self):
        self.config.write_text('[display]\nrenderer = "angle"\n')
        self.config.chmod(0o604)
        inode = self.config.stat().st_ino
        self.assertEqual(self.write(), (1, ""))
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o604)
        self.assertNotEqual(self.config.stat().st_ino, inode)
        self.assertFalse(list(self.directory.glob('config.toml.*')))

    def bundle(self):
        macos = self.directory / 'App/Contents/MacOS'
        resources = self.directory / 'App/Contents/Resources'
        macos.mkdir(parents=True)
        resources.mkdir(parents=True)
        (macos / 'halo').write_text('primary')
        (macos / 'halo').chmod(0o755)
        shutil.copy2(self.child, macos / 'halo-metal')
        for guest in ('halo_guest.elf', 'halo_guest-metal.elf'):
            (resources / guest).write_bytes(b'authored CPU fixture payload')
        return macos, resources

    def test_pair_detection_and_native_standalone_guest_fallback(self):
        macos, resources = self.bundle()
        for library, active in zip(self.libraries, (0, 1)):
            library.host_renderer_set_paths(os.fsencode(macos / 'halo'), os.fsencode(resources))
            self.assertEqual(library.host_renderer_active(), active)
            self.assertEqual(library.host_renderer_can_choose(), 1)
            path = ctypes.create_string_buffer(4096)
            self.assertEqual(library.host_renderer_default_guest(path, len(path)), 1)
            self.assertEqual(Path(os.fsdecode(path.value)).name, 'halo_guest-metal.elf' if active else 'halo_guest.elf')
        for item in (macos / 'halo', macos / 'halo-metal', resources / 'halo_guest.elf', resources / 'halo_guest-metal.elf'):
            contents, mode = item.read_bytes(), item.stat().st_mode
            item.unlink()
            self.assertEqual(self.library.host_renderer_can_choose(), 0)
            item.write_bytes(contents)
            item.chmod(mode)
        (resources / 'halo_guest-metal.elf').unlink()
        path = ctypes.create_string_buffer(4096)
        self.assertEqual(self.libraries[1].host_renderer_default_guest(path, len(path)), 1)
        self.assertEqual(Path(os.fsdecode(path.value)).name, 'halo_guest.elf')
        self.assertEqual(self.library.host_renderer_default_guest(path, 2), 0)

    def launch(self, macos, resources, *arguments):
        return subprocess.run([str(self.driver), str(macos / 'halo'), str(resources),
                               str(macos / 'halo'), *arguments], capture_output=True, text=True, timeout=5)

    def test_dispatch_executes_native_host_with_invite_arguments_intact(self):
        macos, resources = self.bundle()
        arguments = ('halo://join/a-b_c', 'discord-123456789://connect', 'literal argument with spaces')
        result = self.launch(macos, resources, *arguments)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout.splitlines(), ['native:4', f'arg:{macos / "halo-metal"}',
                                                     *[f'arg:{argument}' for argument in arguments]])
        self.assertIn('Renderer dispatch: Native Metal', result.stderr)
        self.assertNotIn('fallback:', result.stdout)

    def test_unavailable_or_unexecutable_native_pair_returns_to_angle(self):
        macos, resources = self.bundle()
        native_guest = resources / 'halo_guest-metal.elf'
        native_guest.unlink()
        result = self.launch(macos, resources)
        self.assertEqual(result.returncode, 0)
        self.assertIn('unavailable', result.stdout)
        native_guest.write_bytes(b'fixture')
        (macos / 'halo-metal').chmod(0o644)
        result = self.launch(macos, resources)
        self.assertEqual(result.returncode, 0)
        self.assertIn('unavailable', result.stdout)
        (macos / 'halo-metal').write_text('not an executable image')
        (macos / 'halo-metal').chmod(0o755)
        result = self.launch(macos, resources)
        self.assertEqual(result.returncode, 0)
        self.assertIn('Could not launch Native Metal', result.stdout)


if __name__ == '__main__':
    unittest.main()
