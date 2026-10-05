"""Compile desktop URI registration against controlled OS calls.

Portable fixtures mock registry and xdg-mime calls and write only temporary
files. Native Windows additionally owns and removes a unique disposable scheme;
native Linux launches a temporary desktop file without changing defaults.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from tools.test_discord_presence import function_source
from tools.windows_build import WINDOWS_ABI_FLAGS


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "port/linux/src"
SECRET = "0123456789abcdef0123456789abcdeffedcba9876543210fedcba9876543210"
SCHEMES = ("halo-og", "discord-1556496882329460736")
WINDOWS_CRT_FORMAT_FLAGS = [
    flag for flag in WINDOWS_ABI_FLAGS
    if flag.split("=", 1)[0] == "-D_CRT_NON_CONFORMING_SWPRINTFS"
]

WINDOWS_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include "posix.h"
typedef wchar_t WCHAR;
typedef unsigned long DWORD;
typedef unsigned char BYTE;
typedef int BOOL;
typedef int HKEY;
enum { TRUE = 1, FALSE = 0, HKEY_CURRENT_USER = 7, KEY_WRITE = 8,
       REG_SZ = 1, ERROR_SUCCESS = 0, CP_UTF8 = 65001, MB_ERR_INVALID_CHARS = 8 };
static WCHAR executable[32768], keys[2][256], values[3][32784];
static int creations, writes, closes, failure, formats;
static char command_line[4096];
/* Model the production Windows CRT's legacy swprintf declaration on every OS.
 * A bounded call accidentally using that name must fail to compile. */
int fixture_legacy_swprintf(WCHAR *buffer, const WCHAR *format, ...);
static int fixture_swprintf_s(WCHAR *buffer, size_t size, const WCHAR *format, ...)
{
    va_list arguments;
    int result;
    assert(buffer && size && format);
    formats++;
    if (failure >= 5 && failure <= 7 && formats == failure - 4) {
        buffer[0] = L'\0';
        return -1;
    }
    va_start(arguments, format);
#ifdef _WIN32
    result = vswprintf_s(buffer, size, format, arguments);
#else
    result = vswprintf(buffer, size, format, arguments);
#endif
    va_end(arguments);
    return result;
}
#ifdef swprintf
#undef swprintf
#endif
#ifdef swprintf_s
#undef swprintf_s
#endif
#define swprintf fixture_legacy_swprintf
#define swprintf_s fixture_swprintf_s
static const char *GetCommandLineA(void) { return command_line; }
static DWORD GetModuleFileNameW(void *module, WCHAR *buffer, DWORD size)
{
    assert(!module);
    if (failure == 1) return 0;
    if (failure == 2) return size;
    assert(wcslen(executable) < size);
    wcscpy(buffer, executable);
    return (DWORD)wcslen(buffer);
}
static int MultiByteToWideChar(unsigned code_page, unsigned flags, const char *text,
                             int bytes, WCHAR *buffer, int size)
{
    assert(code_page == CP_UTF8 && flags == MB_ERR_INVALID_CHARS && bytes == -1);
    size_t length = strlen(text);
    if (length >= (size_t)size) return 0;
    for (size_t i = 0; i <= length; i++) buffer[i] = (unsigned char)text[i];
    return (int)length + 1;
}
static int RegCreateKeyExW(HKEY root, const WCHAR *name, DWORD reserved, WCHAR *class_name,
                          DWORD options, DWORD access, void *security, HKEY *key, DWORD *disposition)
{
    assert(root == HKEY_CURRENT_USER && !reserved && !class_name && !options);
    assert(access == KEY_WRITE && !security && !disposition && creations < 2);
    wcscpy(keys[creations], name);
    *key = ++creations;
    return failure == 3 ? 5 : ERROR_SUCCESS;
}
static int RegSetValueExW(HKEY key, const WCHAR *name, DWORD reserved, DWORD type,
                         const BYTE *bytes, DWORD size)
{
    const WCHAR *text = (const WCHAR *)bytes;
    assert(!reserved && type == REG_SZ && writes < 3);
    assert(size == (wcslen(text) + 1) * sizeof(WCHAR));
    assert((writes < 2 && key == 1) || (writes == 2 && key == 2));
    if (writes == 1) assert(!wcscmp(name, L"URL Protocol") && !*text);
    else assert(!name);
    wcscpy(values[writes++], text);
    return failure == 4 ? 5 : ERROR_SUCCESS;
}
static int RegCloseKey(HKEY key) { assert(key == 1 || key == 2); closes++; return 0; }

/* PRODUCTION_WINDOWS */

int main(int argc, char **argv)
{
    WCHAR scheme[128], expected[32784];
    char argument[4096];
    assert(argc == 3);
    failure = atoi(argv[2]);
    assert(!strcmp(argv[1], "halo-og") || !strcmp(argv[1], "discord-1556496882329460736"));
    /* Spaces, a non-ANSI user name, and a path beyond MAX_PATH. */
    wcscpy(executable, L"C:\\Users\\\u674e\\Halo OG ");
    while (wcslen(executable) < 300) wcscat(executable, L"long directory\\");
    wcscat(executable, L"halo.exe");
    int result = posix_register_url_scheme(argv[1], "Halo OG invite");
    assert(result == !failure);
    if (failure == 1 || failure == 2) assert(!creations && !writes && !closes);
    else if (failure == 5 || failure == 6) assert(!creations && !writes && !closes);
    else if (failure == 7) assert(creations == 1 && writes == 2 && closes == 1);
    else if (failure == 3) assert(creations == 1 && !writes && !closes);
    else {
        assert(creations == 2 && writes == 3 && closes == 2);
        assert(MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, argv[1], -1, scheme, 128));
        wcscpy(expected, L"Software\\Classes\\");
        wcscat(expected, scheme);
        assert(!wcscmp(keys[0], expected));
        wcscat(expected, L"\\shell\\open\\command");
        assert(!wcscmp(keys[1], expected));
        assert(!wcscmp(values[0], L"URL:Halo OG invite"));
        assert(values[2][0] == L'"');
        assert(!wcsncmp(values[2] + 1, executable, wcslen(executable)));
        assert(!wcscmp(values[2] + 1 + wcslen(executable), L"\" \"%1\""));
    }
    snprintf(command_line, sizeof(command_line), "\"C:\\Program Files\\Halo OG\\halo.exe\" \"%s://join/@SECRET@\"", argv[1]);
    assert(posix_command_line_argument(0, argument, sizeof(argument)));
    assert(!strcmp(argument, "C:\\Program Files\\Halo OG\\halo.exe"));
    assert(posix_command_line_argument(1, argument, sizeof(argument)));
    char invite[256]; snprintf(invite, sizeof(invite), "%s://join/@SECRET@", argv[1]);
    assert(!strcmp(argument, invite));
    assert(!posix_command_line_argument(2, argument, sizeof(argument)));
    return 0;
}
'''

WINDOWS_NATIVE_HARNESS = r'''
#include <windows.h>
#include <shellapi.h>
#include <assert.h>
#include <stdio.h>
#include <wchar.h>
#include "posix.h"
/* PRODUCTION_WINDOWS */
int main(void)
{
    int argc;
    WCHAR **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    assert(argv);
    if (argc == 3 && !wcscmp(argv[1], L"--exercise")) {
        char scheme[128];
        WCHAR invite[256];
        assert(WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[2], -1,
                                   scheme, sizeof(scheme), NULL, NULL));
        assert(posix_register_url_scheme(scheme, "Halo OG disposable URI test"));
        wcscpy(invite, argv[2]);
        wcscat(invite, L"://join/@SECRET@");
        assert((INT_PTR)ShellExecuteW(NULL, L"open", invite, NULL, NULL, SW_HIDE) > 32);
    } else {
        WCHAR capture[32768];
        char text[131072];
        DWORD length = GetModuleFileNameW(NULL, capture, sizeof(capture) / sizeof(*capture));
        assert(argc == 2 && length && length < sizeof(capture) / sizeof(*capture));
        WCHAR *separator = wcsrchr(capture, L'\\');
        assert(separator);
        wcscpy(separator + 1, L"launched.txt");
        FILE *file = _wfopen(capture, L"wb");
        assert(file);
        for (int i = 0; i < argc; i++) {
            int bytes = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[i], -1,
                                            text, sizeof(text), NULL, NULL);
            assert(bytes > 0);
            assert(fwrite(text, 1, (size_t)bytes - 1, file) == (size_t)bytes - 1);
            assert(fputc('\n', file) != EOF);
        }
        assert(!fclose(file));
    }
    LocalFree(argv);
    return 0;
}
'''

LINUX_HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#ifdef _WIN32
#include <direct.h>
typedef intptr_t ssize_t;
typedef int pid_t;
char **environ;
#else
#include <sys/wait.h>
#endif
#include "posix.h"
#ifndef WIFEXITED
#define WIFEXITED(status) (((status) & 127) == 0)
#define WEXITSTATUS(status) (((status) >> 8) & 255)
#endif
static const char *scheme, *directory, *executable, *mode;
static int spawn_status, spawns;
static char process_arguments[8192];
static size_t arguments_length;
static const char *fixture_getenv(const char *name)
{
    if (!strcmp(name, "XDG_DATA_HOME")) return !strcmp(mode, "xdg") ? directory : NULL;
    if (!strcmp(name, "HOME")) return !strcmp(mode, "home") ? directory : NULL;
    assert(0); return NULL;
}
static ssize_t fixture_readlink(const char *path, char *buffer, size_t size)
{
    assert(!strcmp(path, "/proc/self/exe"));
    size_t length = strlen(executable);
    if (length > size) length = size;
    memcpy(buffer, executable, length);
    return (ssize_t)length;
}
static int fixture_mkdir(const char *path, unsigned permissions)
{
    assert(permissions == 0755);
#ifdef _WIN32
    if (strlen(path) == 2 && path[1] == ':') return 0;
    return _mkdir(path);
#else
    return mkdir(path, permissions);
#endif
}
static int fixture_spawn(pid_t *process, const char *program, void *actions, void *attributes,
                         char *const arguments[], char *const environment[])
{
    char expected[256];
    (void)environment;
    assert(!actions && !attributes && !strcmp(program, "xdg-mime"));
    assert(!strcmp(arguments[0], program) && !strcmp(arguments[1], "default"));
    snprintf(expected, sizeof(expected), "halo-og-%s.desktop", scheme);
    assert(!strcmp(arguments[2], expected));
    snprintf(expected, sizeof(expected), "x-scheme-handler/%s", scheme);
    assert(!strcmp(arguments[3], expected) && !arguments[4]);
    spawns++; *process = 7;
    return spawn_status == -1 ? ENOENT : 0;
}
static pid_t fixture_waitpid(pid_t process, int *status, int options)
{
    assert(process == 7 && !options);
    *status = spawn_status << 8;
    return process;
}
static int fixture_open(const char *path, int flags)
{ assert(!strcmp(path, "/proc/self/cmdline") && flags == O_RDONLY); return 7; }
static ssize_t fixture_read(int descriptor, void *buffer, size_t size)
{
    assert(descriptor == 7 && size >= arguments_length);
    memcpy(buffer, process_arguments, arguments_length);
    return (ssize_t)arguments_length;
}
static int fixture_close(int descriptor) { assert(descriptor == 7); return 0; }
#define getenv fixture_getenv
#define readlink fixture_readlink
#define mkdir fixture_mkdir
#define posix_spawnp fixture_spawn
#define waitpid fixture_waitpid
#define open fixture_open
#define read fixture_read
#define close fixture_close

/* PRODUCTION_LINUX */

int main(int argc, char **argv)
{
    char invite[256], argument[256];
    assert(argc == 6);
    scheme = argv[1]; mode = argv[2]; directory = argv[3]; executable = argv[4];
    spawn_status = atoi(argv[5]);
    int result = posix_register_url_scheme(scheme, "Halo OG invite");
    snprintf(invite, sizeof(invite), "%s://join/@SECRET@", scheme);
    strcpy(process_arguments, "/opt/Halo OG/halo");
    size_t first = strlen(process_arguments) + 1;
    strcpy(process_arguments + first, invite);
    arguments_length = first + strlen(invite) + 1;
    assert(posix_command_line_argument(1, argument, sizeof(argument)));
    assert(!strcmp(argument, invite));
    assert(!posix_command_line_argument(2, argument, sizeof(argument)));
    printf("%d %d\n", result, spawns);
    return 0;
}
'''


def desktop_launch(entry, invite):
    """Apply the specification's value, quote, and field-code passes."""
    value = next(line.removeprefix("Exec=") for line in entry.splitlines() if line.startswith("Exec="))
    value = re.sub(r"\\([\\sntr])", lambda match: {"\\": "\\", "s": " ", "n": "\n", "t": "\t", "r": "\r"}[match[1]], value)
    words, word, quoted, position = [], [], False, 0
    while position < len(value):
        character = value[position]
        if character == '"':
            quoted = not quoted
        elif character == "\\" and quoted:
            position += 1
            assert value[position] in '\\"`$'
            word.append(value[position])
        elif character == " " and not quoted:
            if word:
                words.append("".join(word))
                word = []
        else:
            word.append(character)
        position += 1
    assert not quoted
    if word:
        words.append("".join(word))
    return [invite if word == "%u" else word.replace("%%", "%") for word in words]


@unittest.skipUnless(shutil.which("clang"), "clang required")
class UrlSchemeRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="halo-og-url-registration-")
        cls.root = Path(cls.temp.name)
        cls.binaries = {}
        windows_source = (ROOT / "port/windows/src/win32_p2p.c").read_text()
        linux_source = (PORT / "posix_net.c").read_text()
        functions = {
            "windows": "\n".join(signature + function_source(windows_source, name) for name, signature in (
                ("posix_register_url_scheme", "int posix_register_url_scheme(const char *scheme, const char *description)"),
                ("posix_command_line_argument", "int posix_command_line_argument(int index, char *buffer, posix_ulong size)"),
            )),
            "linux": "\n".join(signature + function_source(linux_source, name) for name, signature in (
                ("run_program", "static int run_program(char *const arguments[])"),
                ("desktop_exec_path", "static int desktop_exec_path(char *buffer, size_t size, const char *path)"),
                ("desktop_directory", "static int desktop_directory(char *path)"),
                ("posix_register_url_scheme", "int posix_register_url_scheme(const char *scheme, const char *description)"),
                ("posix_command_line_argument", "int posix_command_line_argument(int index, char *buffer, posix_ulong size)"),
            )),
        }
        flags = ["-D_CRT_SECURE_NO_WARNINGS", "-D_CRT_NONSTDC_NO_DEPRECATE"] if sys.platform == "win32" else []
        for platform, harness in (("windows", WINDOWS_HARNESS), ("linux", LINUX_HARNESS)):
            source = cls.root / (platform + ".c")
            source.write_text(harness.replace("/* PRODUCTION_" + platform.upper() + " */", functions[platform]).replace("@SECRET@", SECRET))
            binary = cls.root / (platform + (".exe" if sys.platform == "win32" else ""))
            try:
                format_flags = WINDOWS_CRT_FORMAT_FLAGS if platform == "windows" else []
                subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", *flags, *format_flags,
                                str(source), "-I" + str(PORT), "-o", str(binary)], check=True)
            except Exception:
                cls.temp.cleanup()
                raise
            cls.binaries[platform] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(dir=self.root))

    def linux(self, scheme="halo-og", mode="xdg", executable="/opt/Halo OG/halo", status=0, directory=None):
        result = subprocess.run([str(self.binaries["linux"]), scheme, mode,
                                 (directory or self.directory / "new" / "data").as_posix(), executable, str(status)],
                                capture_output=True, text=True, check=True)
        return tuple(map(int, result.stdout.split()))

    def desktop_file(self, scheme="halo-og", mode="xdg"):
        base = self.directory / "new" / "data"
        if mode == "home":
            base /= ".local/share"
        return base / "applications" / f"halo-og-{scheme}.desktop"

    def test_windows_registers_og_and_discord_with_unicode_long_path_and_quoted_uri(self):
        for scheme in SCHEMES:
            with self.subTest(scheme=scheme):
                subprocess.run([str(self.binaries["windows"]), scheme, "0"], check=True)

    def test_windows_reports_os_failures_without_using_a_truncated_path(self):
        for failure in range(1, 5):
            with self.subTest(failure=failure):
                subprocess.run([str(self.binaries["windows"]), "halo-og", str(failure)], check=True)

    def test_windows_reports_each_formatting_failure_before_using_partial_output(self):
        for failure in (5, 6, 7):
            with self.subTest(failure=failure):
                subprocess.run([str(self.binaries["windows"]), "halo-og", str(failure)], check=True)

    def wait_for_capture(self, capture, expected):
        deadline = time.monotonic() + 10
        actual = None
        while time.monotonic() < deadline:
            try:
                actual = capture.read_text(encoding="utf-8").splitlines()
            except (FileNotFoundError, UnicodeDecodeError):
                pass
            if actual == expected:
                return
            time.sleep(0.01)
        self.assertEqual(actual, expected)

    @unittest.skipUnless(sys.platform == "win32", "native Windows registry and ShellExecute required")
    def test_native_windows_shell_launch_preserves_unicode_path_and_invite(self):
        import ctypes
        from ctypes import wintypes
        import winreg

        scheme = "halo-og-uri-test-" + uuid.uuid4().hex
        key_name = "Software\\Classes\\" + scheme
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name):
                self.fail("Disposable URI scheme unexpectedly exists")
        except FileNotFoundError:
            pass
        delete_tree = ctypes.WinDLL("advapi32").RegDeleteTreeW
        delete_tree.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
        delete_tree.restype = wintypes.LONG
        # This key was absent and is owned exclusively by this test. Cleanup
        # also removes any partially written registration after a failure.
        try:
            probe = self.directory / "Halo OG \u674e with spaces" / "probe.exe"
            probe.parent.mkdir()
            source = self.directory / "native_windows.c"
            production = "int posix_register_url_scheme(const char *scheme, const char *description)" + function_source(
                (ROOT / "port/windows/src/win32_p2p.c").read_text(), "posix_register_url_scheme")
            source.write_text(WINDOWS_NATIVE_HARNESS.replace("/* PRODUCTION_WINDOWS */", production).replace("@SECRET@", SECRET))
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS",
                            *WINDOWS_CRT_FORMAT_FLAGS,
                            str(source), "-I" + str(PORT), "-ladvapi32", "-lshell32", "-o", str(probe)], check=True)
            subprocess.run([str(probe), "--exercise", scheme], check=True, capture_output=True, text=True, timeout=15)
            self.wait_for_capture(probe.parent / "launched.txt", [str(probe), f"{scheme}://join/{SECRET}"])
        finally:
            # HKEY_CURRENT_USER is the sign-extended predefined Win32 handle.
            status = delete_tree(wintypes.HKEY(-2147483647), key_name)
            self.assertIn(status, (0, 2), "Could not remove the disposable URI registry key")

    def test_linux_first_run_creates_xdg_and_home_parents_for_both_handlers(self):
        for mode in ("xdg", "home"):
            for scheme in SCHEMES:
                with self.subTest(mode=mode, scheme=scheme):
                    self.assertEqual(self.linux(scheme=scheme, mode=mode), (1, 1))
                    entry = self.desktop_file(scheme, mode).read_text()
                    self.assertIn(f"MimeType=x-scheme-handler/{scheme};\n", entry)
                    self.assertEqual(desktop_launch(entry, f"{scheme}://join/{SECRET}"),
                                     ["/opt/Halo OG/halo", f"{scheme}://join/{SECRET}"])

    def test_linux_escapes_executable_characters_without_changing_uri_argument(self):
        executable = '/opt/Halo OG $cash `tick` "quote" \\backslash 100%/halo'
        self.assertEqual(self.linux(executable=executable), (1, 1))
        invite = f"halo-og://join/{SECRET}"
        self.assertEqual(desktop_launch(self.desktop_file().read_text(), invite), [executable, invite])

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("gio"), "native Linux gio required")
    def test_native_linux_desktop_launcher_preserves_executable_path_and_invite(self):
        probe = self.directory / 'Halo OG $cash `tick` "quote" \\backslash 100%' / "halo"
        probe.parent.mkdir()
        capture = self.directory / "launched.txt"
        source = self.directory / "probe.c"
        source.write_text('#include <stdio.h>\nint main(int argc,char **argv){'
                          f'FILE *file=fopen({json.dumps(str(capture))},"w");if(!file)return 1;'
                          'for(int i=0;i<argc;i++)fprintf(file,"%s\\n",argv[i]);return fclose(file)!=0;}\n')
        subprocess.run(["clang", str(source), "-o", str(probe)], check=True)
        self.assertEqual(self.linux(executable=str(probe)), (1, 1))
        invite = f"halo-og://join/{SECRET}"
        subprocess.run(["gio", "launch", str(self.desktop_file()), invite], check=True,
                       capture_output=True, text=True, timeout=10)
        self.wait_for_capture(capture, [str(probe), invite])

    def test_linux_retries_missing_or_failed_xdg_mime_with_unchanged_entry(self):
        for status in (-1, 1):
            with self.subTest(status=status):
                self.assertEqual(self.linux(status=status), (0, 1))
                self.assertEqual(self.linux(), (1, 1))

    def test_linux_does_not_modify_upstream_desktop_handler(self):
        upstream = self.directory / "new/data/applications/halo-ce-universal-halo.desktop"
        upstream.parent.mkdir(parents=True)
        upstream.write_text("upstream handler\n")
        self.assertEqual(self.linux(), (1, 1))
        self.assertEqual(upstream.read_text(), "upstream handler\n")

    def test_linux_rejects_missing_environment_truncated_path_and_failed_write(self):
        self.assertEqual(self.linux(mode="missing"), (0, 0))
        self.assertEqual(self.linux(executable="/" + "a" * 4096), (0, 0))
        self.assertEqual(self.linux(executable="/opt/invalid=path/halo"), (0, 0))
        blocked = self.directory / "blocked"
        blocked.write_text("parent is a file")
        self.assertEqual(self.linux(directory=blocked), (0, 0))


if __name__ == "__main__":
    unittest.main()
