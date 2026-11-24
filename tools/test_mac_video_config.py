"""CPU checks for Metal settings persistence and legacy Mac renderer preferences."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

from tools.test_audio_settings import CONFIG_HARNESS
from tools.test_input_bindings import PREFIX, PORT, ROOT, SDL

FAULT_PREFIX = r'''
#include <unistd.h>
int config_test_fsync(int);
int config_test_rename(const char *,const char *);
size_t config_test_fwrite(const void *,size_t,size_t,FILE *);
int config_test_fclose(FILE *);
#define fsync config_test_fsync
#define rename config_test_rename
#define fwrite config_test_fwrite
#define fclose config_test_fclose
'''

MAIN = r'''
int main(int argc,char **argv) {
    assert(argc>=2 && (argc-2)%3==0);
    struct config_update updates[32];
    unsigned count=(unsigned)(argc-2)/3;assert(count<32);
    for(unsigned i=0;i<count;i++) {
        updates[i].name=argv[2+3*i];updates[i].number=strtod(argv[4+3*i],NULL);
        updates[i].type=!strcmp(argv[3+3*i],"number") ? _config_update_number:_config_update_string;
        updates[i].string=!strcmp(argv[3+3*i],"null") ? NULL:argv[4+3*i];
        if(!strcmp(argv[3+3*i],"invalid"))updates[i].type=(enum config_update_type)99;
    }
    char path[1024];snprintf(path,sizeof(path),"%s/config.toml",getenv("HALO_SAVE_ROOT"));
    if(!strcmp(argv[1],"cold_invalid")) {
        assert(!config_write_values(updates,count));assert(access(path,F_OK));
        puts("0");return 0;
    }
    if(!strcmp(argv[1],"defaults")) {
        assert(config_integer("display.render_height")==0);
        assert(config_boolean("display.interpolation") && config_boolean("display.high_res_hud"));
        puts("1");return 0;
    }
    if(!strcmp(argv[1],"display")) {
        printf("%ld %d %d %ld\n",config_integer("display.render_height"),config_boolean("display.interpolation"),
            config_boolean("display.high_res_hud"),config_integer("display.frame_limit"));
        return 0;
    }
    /* Warm the cache through an identical registered boolean save without
       completing missing defaults or altering the test's original text. */
    const char *key="display.vsync";double same=1;
    assert(config_write_numbers(&key,&same,1));
    if(!strcmp(argv[1],"legacy")) {
        assert(config_boolean("display.vsync") && config_integer("display.frame_limit")==120);
        assert(config_integer("display.render_height")==1080 && !strcmp(config_string("display.anti_aliasing"),"fxaa"));
        assert(!strcmp(config_string("game.language"),"fr"));
        puts("1");return 0;
    }
    const char *old_aa=config_string("display.anti_aliasing");
    char *aa_copy=strdup(old_aa);assert(aa_copy);
    if(!strcmp(argv[1],"readonly"))assert(!chmod(path,0400));
    failure_mode=atoi(argv[1]);
    int result=config_write_values(updates,count);failure_mode=0;
    assert(!strcmp(old_aa,aa_copy));
    if(result) {
        for(unsigned i=0;i<count;i++) {
            if(updates[i].type==_config_update_string)assert(!strcmp(config_string(updates[i].name),updates[i].string));
            else if(!strcmp(updates[i].name,"display.vsync"))assert(config_boolean(updates[i].name)==(updates[i].number!=0));
            else assert(config_integer(updates[i].name)==updates[i].number);
        }
        if(!strcmp(argv[1],"twice")) {
            const char *first_aa=config_string("display.anti_aliasing");
            char *first_aa_copy=strdup(first_aa);assert(first_aa_copy);
            const struct config_update reset={"display.anti_aliasing",_config_update_string,0,"off"};
            assert(config_write_values(&reset,1));
            assert(!strcmp(first_aa,first_aa_copy) && !strcmp(old_aa,aa_copy));
            free(first_aa_copy);
        }
    } else {
        assert(!strcmp(config_string("display.anti_aliasing"),aa_copy));
        assert(config_boolean("display.vsync"));
    }
    assert(!chmod(path,0600));free(aa_copy);printf("%d\n",result);return 0;
}
'''

ORIGINAL = ('# player notes\n[display] # display\nrenderer = "angle" # engine\n'
            "anti_aliasing = 'off' # edges\nvsync = true\nframe_limit = 30\nrender_height = 480\n"
            'custom = "é, # []"\n')
CHANGES = [('display.anti_aliasing', 'string', 'fxaa'),
           ('display.vsync', 'number', '0'), ('display.frame_limit', 'number', '120'),
           ('display.render_height', 'number', '0')]


@unittest.skipUnless(shutil.which("clang") and (SDL / "include/SDL3/SDL.h").exists(),
                     "clang and SDL3 headers required")
class MacVideoConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-mixed-video-config-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        prefix, probe = cls.directory / "prefix.h", cls.directory / "probe.c"
        prefix.write_text(PREFIX + FAULT_PREFIX)
        logging = r"""void platform_log(const char *format,...) {
            va_list args;va_start(args,format);vfprintf(stderr,format,args);va_end(args);fputc('\n',stderr);
        }"""
        prelude = CONFIG_HARNESS.split("int main(", 1)[0].replace(
            "void platform_log(const char *format,...) { (void)format; }", logging)
        probe.write_text("#include <stdarg.h>\n" + prelude + MAIN)
        cls.executable = cls.directory / "probe"
        result = subprocess.run(["clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pthread",
            "-fsanitize=address,undefined", "-DHALO_ANDROID=1", "-DHALO_MACOS=1",
            "-include", str(prefix), f"-I{PORT}", f"-I{SDL / 'include'}", f"-I{ROOT / 'port/third_party/tomlc17'}",
            str(probe), str(PORT / "port_config.c"), str(ROOT / "port/third_party/tomlc17/tomlc17.c"),
            "-o", str(cls.executable)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)

    def save(self, content=ORIGINAL, updates=CHANGES, mode="0", success=True, legacy_notice=None):
        with tempfile.TemporaryDirectory(prefix="halo-video-config-save-") as folder:
            root = Path(folder)
            path = root / "config.toml"
            if content is not None:
                path.write_bytes(content.encode())
            env = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
            env.update(HALO_SAVE_ROOT=folder, HALO_DATA_ROOT=folder)
            result = subprocess.run([str(self.executable), mode, *(word for update in updates for word in update)],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), str(int(success)))
            if legacy_notice is not None:
                self.assertEqual("using native Metal for legacy display.renderer" in result.stderr, legacy_notice)
                self.assertNotIn("unknown setting display.renderer", result.stderr)
            self.assertEqual(sorted(p.name for p in root.iterdir()),
                             [] if mode == "cold_invalid" else ["config.toml"])
            saved = path.read_text() if path.exists() else None
            if not success:
                self.assertEqual(saved, content)
            elif mode != "twice":
                parsed = tomllib.loads(saved)
                for key, kind, value in updates:
                    section, name = key.split(".")
                    self.assertEqual(parsed[section][name], value if kind == "string" else float(value))
            return saved

    def test_mixed_batch_preserves_unrelated_text_and_comments(self):
        expected = (ORIGINAL.replace("'off'", '"fxaa"')
                    .replace("vsync = true", "vsync = false").replace("frame_limit = 30", "frame_limit = 120")
                    .replace("render_height = 480", "render_height = 0"))
        self.assertEqual(self.save(), expected)

    def test_quoted_dotted_inline_and_multiline_string_tokens(self):
        forms = [
            '["display"]\r\n"renderer"=\'angle\' # r\r\n"anti_aliasing"="off"\r\n"vsync"=true\r\n',
            'display.renderer="angle"\ndisplay.anti_aliasing=\'off\'\ndisplay.vsync=true\n',
            'display={renderer="angle",anti_aliasing="off",vsync=true,custom="é, # []"}\n',
            '[display]\nrenderer="""\nangle"""\nanti_aliasing=\'\'\'off\'\'\'\nvsync=true\n',
        ]
        for original in forms:
            with self.subTest(original=original):
                self.save(original, CHANGES[:2], legacy_notice=True)

    def test_strings_round_trip_quotes_backslashes_control_characters_and_unicode(self):
        for value in ('français, # [] "quote" \\ path\n\tend', 'x' * 1024, ''):
            with self.subTest(value=value):
                self.save(updates=[('game.language', 'string', value)])

    def test_returned_string_pointers_remain_valid_across_later_saves(self):
        self.save(mode="twice")

    def test_short_write_flush_close_rename_and_readonly_fail_without_partial_update(self):
        for mode in ('1', '2', '3', '4', 'readonly'):
            with self.subTest(mode=mode):
                self.save(mode=mode, success=False)

    def test_whole_batch_rejects_unknown_duplicate_wrong_kind_null_and_nonfinite(self):
        invalid = [('unknown', 'number', '0'), ('display.renderer', 'number', '1'),
                   ('display.renderer', 'string', 'angle'),
                   ('display.vsync', 'string', 'false'), ('display.anti_aliasing', 'null', ''),
                   ('display.frame_limit', 'number', 'nan'), ('display.frame_limit', 'number', '1.5'),
                   ('display.vsync', 'number', '2'), ('display.anti_aliasing', 'invalid', 'off')]
        for bad in invalid:
            with self.subTest(bad=bad):
                self.save(updates=[CHANGES[0], bad], success=False)
        self.save(updates=[CHANGES[0], CHANGES[0]], success=False)

    def test_invalid_batch_cannot_create_missing_config_or_write_defaults(self):
        self.save(content=None, updates=[CHANGES[0], ('unknown', 'number', '0')],
                  mode="cold_invalid", success=False)

    def test_existing_wrong_type_rejects_entire_mixed_save(self):
        self.save(ORIGINAL.replace("'off'", "1"), success=False)

    def test_legacy_renderer_accepts_old_files_and_preserves_mac_settings(self):
        for previous in ("angle", "metal"):
            with self.subTest(previous=previous):
                original = (ORIGINAL.replace('"angle"', f'"{previous}"').replace("'off'", "'fxaa'")
                            .replace("frame_limit = 30", "frame_limit = 120")
                            .replace("render_height = 480", "render_height = 1080") + '[game]\nlanguage = "fr"\n')
                self.assertEqual(self.save(original, [], mode="legacy", legacy_notice=previous == "angle"), original)

    def test_fresh_metal_config_omits_retired_renderer(self):
        config = tomllib.loads(self.save(None, [], mode="defaults", legacy_notice=False))
        self.assertNotIn("renderer", config["display"])
        self.assertEqual(config["display"]["anti_aliasing"], "off")
        self.assertEqual(config["display"]["frame_limit"], 0)
        self.assertEqual(config["display"]["render_height"], 0)
        self.assertIs(config["display"]["interpolation"], True)
        self.assertIs(config["display"]["high_res_hud"], True)
        self.assertEqual(config["display"]["defaults_revision"], 1)

    def load_display(self, content):
        """Start with an existing settings file; return what the game uses and the file it leaves."""
        with tempfile.TemporaryDirectory(prefix="halo-display-defaults-") as folder:
            path = Path(folder) / "config.toml"
            path.write_text(content)
            env = {key: value for key, value in os.environ.items() if not key.startswith("HALO_")}
            env.update(HALO_SAVE_ROOT=folder, HALO_DATA_ROOT=folder)
            result = subprocess.run([str(self.executable), "display"], env=env, capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return tuple(map(int, result.stdout.split())), path.read_text()

    def test_settings_from_0_6_that_never_changed_the_picture_move_to_the_new_defaults(self):
        untouched = ('# my notes\n[display]\nvsync = false\ninterpolation = false # smooth\nframe_limit = 0\n'
                     'render_height = 480\nhigh_res_hud = false\n\n[audio]\nvolume = 0.5\n')
        used, saved = self.load_display(untouched)
        self.assertEqual(used, (0, 1, 1, 0))
        display = tomllib.loads(saved)["display"]
        self.assertEqual((display["render_height"], display["interpolation"], display["high_res_hud"]),
                         (0, True, True))
        self.assertEqual(display["defaults_revision"], 1)
        self.assertIs(display["vsync"], False)
        self.assertEqual(tomllib.loads(saved)["audio"]["volume"], 0.5)
        self.assertIn("# my notes", saved)
        self.assertIn("interpolation = true # smooth", saved)
        # The offer is made once: choosing the Xbox picture afterwards is kept.
        chosen = saved.replace("render_height = 0", "render_height = 480").replace(
            "interpolation = true", "interpolation = false").replace("high_res_hud = true", "high_res_hud = false")
        self.assertEqual(self.load_display(chosen), ((480, 0, 0, 0), chosen))

    def test_settings_that_changed_any_picture_option_keep_all_of_them(self):
        base = ('[display]\ninterpolation = false\nframe_limit = 0\nrender_height = 480\n'
                'high_res_hud = false\n')
        for change, expected in (("render_height = 720", (720, 0, 0, 0)),
                                 ("interpolation = true", (480, 1, 0, 0)),
                                 ("high_res_hud = true", (480, 0, 1, 0)),
                                 ("frame_limit = 30", (480, 0, 0, 30))):
            with self.subTest(change=change):
                key = change.split(" = ")[0]
                original = "\n".join(change if line.startswith(key + " ") else line
                                     for line in base.split("\n"))
                used, saved = self.load_display(original)
                self.assertEqual(used, expected)
                self.assertTrue(saved.startswith(original))

    def test_profile_naming_only_some_picture_options_keeps_the_ones_it_names(self):
        used, saved = self.load_display('[display]\ninterpolation = false\nhigh_res_hud = false\n')
        # The options it names stay; the ones it omits take this version's defaults.
        self.assertEqual(used, (0, 0, 0, 0))
        self.assertIn("interpolation = false", saved)
        self.assertIn("high_res_hud = false", saved)


if __name__ == "__main__":
    unittest.main()
