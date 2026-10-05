from pathlib import Path
import hashlib
import tempfile
import unittest

from metal_roof_angle_reprepare import flatten, initial_config, setting_defaults, verify


class CompleteConfigPreparationTests(unittest.TestCase):
    def test_source_defaults_decode_quoted_toml_and_joined_c_strings(self):
        source = '''
        { "audio.enabled", _config_boolean, "true", NULL },
        { "input.mouse_sensitivity", _config_real, "1.0", NULL },
        { "game.language", _config_string, "\\\"" "\\\"", NULL },
        '''
        self.assertEqual(setting_defaults(source), {
            "audio.enabled": True, "input.mouse_sensitivity": 1.0, "game.language": ""})

    def test_retained_template_reconstructs_exact_path_port_bytes(self):
        source = '''config = f"""[debug]\nscreenshot_directory=\"{folder / 'screenshots'}\"\ntelnet_console_port={23870+index}\n"""'''
        self.assertEqual(initial_config(source, Path("/tmp/isolated"), 2),
                         '[debug]\nscreenshot_directory="/tmp/isolated/screenshots"\ntelnet_console_port=23872\n')
        self.assertEqual(flatten({"display": {"vsync": True}, "debug": {"exit_after": 30.0}}),
                         {"display.vsync": True, "debug.exit_after": 30.0})

    def test_hash_exception_is_exact_and_rejects_second_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder) / "a", Path(folder) / "b"
            a.write_bytes(b"a"); b.write_bytes(b"b")
            expected = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (a, b)}
            a.write_bytes(b"changed")
            self.assertEqual(set(verify(expected, [str(a)])), {str(a)})
            with self.assertRaises(ValueError):
                verify(expected)
            b.write_bytes(b"changed too")
            with self.assertRaises(ValueError):
                verify(expected, [str(a)])


if __name__ == "__main__":
    unittest.main()
