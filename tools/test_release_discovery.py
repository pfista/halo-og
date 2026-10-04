"""Authored release metadata and native tests; no installed application updates."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import release_discovery as identity

ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
DATE = "2026-10-03T12:00:00Z"
ASSET = "halo-windows-release.zip" if sys.platform == "win32" else "halo-linux-release.zip"
OTHER = "b" * 40


def release(tag="test-v0.3.0-net11-next", sha=OTHER, date="2026-10-04T12:00:00Z", asset=ASSET):
    base = f"https://github.com/pfista/halo-og/releases/download/{tag}/"
    return {"tag_name": tag, "draft": False, "prerelease": True, "created_at": date,
            "published_at": "2026-10-04T13:00:00Z",
            "body": f"All four builds use source [{sha}](https://github.com/pfista/halo-og/commit/{sha}).",
            "assets": [{"name": name, "state": "uploaded", "browser_download_url": base + name}
                       for name in (asset, "provenance.json", "SHA256SUMS")],
            "author": {"login": "pfista", "description": "Unicode \u2764 and escaped \"strings\""}}


SDL = r'''
#ifndef TEST_SDL_H
#define TEST_SDL_H
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
typedef struct SDL_Window { int unused; } SDL_Window;
typedef struct SDL_Thread { int unused; } SDL_Thread;
typedef struct SDL_AtomicInt { int value; } SDL_AtomicInt;
#define SDLCALL
#define SDL_WINDOW_FULLSCREEN 1
#define SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT 1
#define SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT 2
#define SDL_MESSAGEBOX_INFORMATION 4
typedef struct SDL_MessageBoxButtonData { unsigned flags; int buttonID; const char *text; } SDL_MessageBoxButtonData;
typedef struct SDL_MessageBoxData { unsigned flags; SDL_Window *window; const char *title,*message; int numbuttons; const SDL_MessageBoxButtonData *buttons; void *colorScheme; } SDL_MessageBoxData;
static int SDL_SetAtomicInt(SDL_AtomicInt *a,int value) { int old=a->value; a->value=value; return old; }
static int SDL_GetAtomicInt(SDL_AtomicInt *a) { return a->value; }
static bool SDL_CompareAndSwapAtomicInt(SDL_AtomicInt *a,int old,int value) { if(a->value!=old)return false; a->value=value; return true; }
SDL_Thread *SDL_CreateThread(int (*fn)(void*), const char*, void*);
void SDL_DetachThread(SDL_Thread*);
void *SDL_LoadFile(const char*,size_t*);
static void SDL_free(void *p) { free(p); }
unsigned SDL_GetWindowFlags(SDL_Window*);
bool SDL_SetWindowFullscreen(SDL_Window*,bool);
bool SDL_ShowMessageBox(const SDL_MessageBoxData*,int*);
bool SDL_OpenURL(const char*);
const char *SDL_GetError(void);
#endif
'''

HARNESS = r'''
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <SDL3/SDL.h>
#define HALO_OG_RELEASE_DISCOVERY 1
#define HALO_OG_SOURCE_REVISION "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
#define HALO_OG_SOURCE_DATE "2026-10-03T12:00:00Z"
#include "release_discovery.c"
static char fixture_path[1024], opened[256];
static int checks, dialogs, answer, writes, auto_check=1, hidden, fullscreen=1;
void platform_log(const char *fmt, ...) { (void)fmt; }
int config_boolean(const char *name) { return !strcmp(name,"update.auto") ? auto_check : hidden; }
double config_real(const char *name) { (void)name; return 0; }
const char *config_string(const char *name) { (void)name; return ""; }
int config_write_boolean(const char *name,int value) { assert(!strcmp(name,"update.auto")); writes++; auto_check=value; return 1; }
int update_make_private_temporary_directory(char *path,int capacity) { assert(capacity>32); strcpy(path,"fixture-temporary"); return 1; }
void update_delete_file(const char *path) { assert(!strcmp(path,"fixture-temporary/release-check.json") || !strcmp(path,"fixture-temporary")); }
int update_download_limited(const char *url,const char *path,unsigned long long bytes, update_progress_proc progress,void *context,char *error,int size) {
    assert(!strcmp(url,HALO_RELEASE_DISCOVERY_URL)); assert(!strcmp(path,"fixture-temporary/release-check.json"));
    assert(bytes==HALO_RELEASE_DISCOVERY_BYTES && !progress && !context && error && size>0); checks++; return 1;
}
void *SDL_LoadFile(const char *path,size_t *size) {
    FILE *f; char *data; (void)path;
    f=fopen(fixture_path,"rb"); assert(f); fseek(f,0,SEEK_END); *size=(size_t)ftell(f); rewind(f);
    data=malloc(*size+1); assert(data); assert(fread(data,1,*size,f)==*size); data[*size]=0; fclose(f); return data;
}
SDL_Thread *SDL_CreateThread(int (*fn)(void*),const char *name,void *context) { static SDL_Thread thread; (void)name; fn(context); return &thread; }
void SDL_DetachThread(SDL_Thread *thread) { assert(thread); }
unsigned SDL_GetWindowFlags(SDL_Window *window) { assert(window); return fullscreen ? SDL_WINDOW_FULLSCREEN : 0; }
bool SDL_SetWindowFullscreen(SDL_Window *window,bool on) { assert(window); fullscreen=on; return true; }
bool SDL_ShowMessageBox(const SDL_MessageBoxData *box,int *chosen) {
    assert(!strcmp(box->title,"Halo OG update available")); assert(strstr(box->message,"GitHub"));
    assert(box->numbuttons==3); assert(!strcmp(box->buttons[0].text,"Open download")); dialogs++; *chosen=answer; return true;
}
bool SDL_OpenURL(const char *url) { snprintf(opened,sizeof(opened),"%s",url); return true; }
const char *SDL_GetError(void) { return "fixture"; }
int main(int argc,char **argv) {
    struct halo_release_notice notice;
    SDL_Window window;
    char *data; size_t size;
    assert(argc>=3); snprintf(fixture_path,sizeof(fixture_path),"%s",argv[2]);
    if(!strcmp(argv[1],"parse")) {
        assert(argc==6); data=SDL_LoadFile("fixture",&size);
        if(halo_release_discovery_parse(data,size,argv[3],argv[4],argv[5],&notice))
            printf("%s\n%s\n%s\n%s\n",notice.tag,notice.source_sha,notice.source_date,notice.download_url);
        free(data); return 0;
    }
    if(!strcmp(argv[1],"hidden"))hidden=1;
    if(!strcmp(argv[1],"disabled"))auto_check=0;
    halo_release_discovery_start();
    if(hidden || !auto_check) { assert(!checks && !dialogs); return 0; }
    assert(checks==1 && release_state.value==release_available);
    halo_release_discovery_start(); assert(checks==1);
    halo_release_discovery_poll(&window); assert(!dialogs && !opened[0]);
    halo_release_discovery_set_main_menu(0); halo_release_discovery_poll(&window); assert(!dialogs);
    halo_release_discovery_set_main_menu(1);
    answer=!strcmp(argv[1],"open") ? 1 : !strcmp(argv[1],"stop") ? 2 : 0;
    halo_release_discovery_poll(&window); assert(dialogs==1 && fullscreen);
    if(answer==1)assert(strstr(opened,"https://github.com/pfista/halo-og/releases/download/") == opened);
    else assert(!opened[0]);
    if(answer==2)assert(writes==1 && !auto_check);
    else assert(!writes && auto_check);
    halo_release_discovery_poll(&window); assert(dialogs==1); return 0;
}
'''


class ReleaseDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            raise RuntimeError("A native C compiler is required for release-discovery tests")
        cls.temporary = tempfile.TemporaryDirectory(prefix="halo-release-fixture-")
        cls.work = Path(cls.temporary.name)
        (cls.work / "SDL3").mkdir()
        (cls.work / "SDL3/SDL.h").write_text(SDL)
        (cls.work / "fixture.c").write_text(HARNESS)
        cls.binary = cls.work / ("fixture.exe" if sys.platform == "win32" else "fixture")
        command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror"]
        if sys.platform == "win32":
            command += ["-D_CRT_SECURE_NO_WARNINGS"]
        subprocess.run([*command, "-I" + str(cls.work), "-I" + str(ROOT / "port/linux/src"),
                        str(cls.work / "fixture.c"), "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_fixture(self, mode, records, asset=ASSET, sha=SHA, date=DATE):
        path = self.work / "metadata.json"
        path.write_bytes(records if isinstance(records, bytes) else json.dumps(records).encode())
        command = [str(self.binary), mode, str(path)]
        if mode == "parse": command += [asset, sha, date]
        return subprocess.check_output(command, text=True).splitlines()

    def test_selects_newest_source_independent_of_tags_and_api_order(self):
        old = release(tag="test-z99", sha="c" * 40, date="2026-10-04T01:00:00Z")
        newer = release(tag="test-a1", date="2026-10-04T12:00:00Z")
        result = self.run_fixture("parse", [old, newer])
        self.assertEqual(result, [newer["tag_name"], OTHER, newer["created_at"], newer["assets"][0]["browser_download_url"]])
        self.assertEqual(self.run_fixture("parse", [newer, old]), result)

    def test_no_same_commit_equal_timestamp_or_republished_old_commit_downgrade(self):
        for record in [release(sha=SHA), release(date=DATE), release(date="2026-10-02T12:00:00Z")]:
            with self.subTest(record=record): self.assertEqual(self.run_fixture("parse", [record]), [])

    def test_requires_published_complete_platform_release_and_source_claim(self):
        candidates = []
        for key, value in [("draft", True), ("published_at", None), ("body", None), ("created_at", "2026-02-30T12:00:00Z")]:
            record = release(); record[key] = value; candidates.append(record)
        for name in (ASSET, "provenance.json", "SHA256SUMS"):
            record = release(); record["assets"] = [a for a in record["assets"] if a["name"] != name]; candidates.append(record)
        record = release(); record["assets"][0]["state"] = "new"; candidates.append(record)
        for record in candidates:
            with self.subTest(record=record): self.assertEqual(self.run_fixture("parse", [record]), [])

    def test_accepts_mac_asset_and_prereleases_without_latest_endpoint(self):
        self.assertTrue(self.run_fixture("parse", [release(asset="Halo-OG-macos-arm64.dmg")], asset="Halo-OG-macos-arm64.dmg"))
        self.assertEqual(self.run_fixture("parse", [release()], asset="halo-android-release.zip"), [])

    def test_rejects_foreign_redirect_urls_traversal_duplicate_and_ambiguous_identity(self):
        for url in ("http://github.com/pfista/halo-og/asset", "https://github.com.evil.test/asset",
                    "https://github.com/cybersecurity/halo-ce-universal/asset",
                    release()["assets"][0]["browser_download_url"] + "?redirect=1"):
            record = release(); record["assets"][0]["browser_download_url"] = url
            self.assertEqual(self.run_fixture("parse", [record]), [])
        for tag in ("../test", ".test", "test/slash", "test%2fother", "test?query"):
            self.assertEqual(self.run_fixture("parse", [release(tag=tag)]), [])
        record = release(); record["assets"].append(copy.deepcopy(record["assets"][0]))
        self.assertEqual(self.run_fixture("parse", [record]), [])
        record = release(); record["body"] += f" [old](https://github.com/pfista/halo-og/commit/{SHA})"
        self.assertEqual(self.run_fixture("parse", [record]), [])

    def test_malformed_oversized_and_deep_metadata_fail_closed(self):
        valid = json.dumps([release()]).encode()
        for data in (valid[:-1], valid + b"null", valid.replace(b'"draft": false', b'"draft": false, "draft": true'),
                     valid.replace(b'"draft": false', b'"draft": falsee'), b"[" * 18 + b"]" * 18,
                     b" " * (256 * 1024 + 1), json.dumps([release()] * 6).encode()):
            with self.subTest(data=data[:100]): self.assertEqual(self.run_fixture("parse", data), [])

    def test_notifications_defer_until_local_menu_and_only_open_browser_once(self):
        for mode in ("open", "later", "stop", "hidden", "disabled"):
            with self.subTest(mode=mode): self.run_fixture(mode, [release()])

    def test_native_menu_hook_excludes_mac_mobile_and_retail(self):
        source = (ROOT / "source/main/main.c").read_text()
        self.assertIn("halo_release_discovery_set_main_menu(main_globals.main_menu_scenario_loaded &&", source)
        self.assertIn("main_globals.connection == _game_connection_local", source)
        self.assertEqual(source.count("!defined(HALO_MACOS) && !defined(HALO_IOS) && !defined(HALO_ANDROID)"), 2)
        updater = (ROOT / "port/linux/src/updater.c").read_text()
        browser = updater[updater.index("#if HALO_OG_RELEASE_DISCOVERY"):updater.index("\n#else\n", updater.index("#if HALO_OG_RELEASE_DISCOVERY"))]
        self.assertNotIn("update_replace_file", browser)
        self.assertNotIn("update_launch", browser)
        self.assertIn("halo_release_discovery_start", browser)

    def test_production_discovery_and_wrapper_compile_for_windows_i686_abi(self):
        clang = shutil.which("clang")
        if not clang:
            self.skipTest("clang is needed for the Windows ABI compile probe")
        # Narrow authored CRT declarations replace only the absent Windows SDK.
        # Both actual production translation units are compiled, not a mirrored
        # implementation or a native-host substitute for their Windows ABI.
        sdk = self.work / "windows-sdk"
        sdk.mkdir(exist_ok=True)
        headers = {
            "stddef.h": "#ifndef FIXTURE_STDDEF\n#define FIXTURE_STDDEF\ntypedef __SIZE_TYPE__ size_t;\n#define NULL ((void*)0)\n#endif\n",
            "stdbool.h": "#define bool _Bool\n#define true 1\n#define false 0\n",
            "stdlib.h": "void free(void*);\n",
            "stdio.h": "#include <stddef.h>\nint snprintf(char*,size_t,const char*,...);\n",
            "string.h": "#include <stddef.h>\nsize_t strlen(const char*);\nint strcmp(const char*,const char*);\nint memcmp(const void*,const void*,size_t);\nvoid *memcpy(void*,const void*,size_t);\nvoid *memset(void*,int,size_t);\nchar *strstr(const char*,const char*);\n",
        }
        for name, text in headers.items(): (sdk / name).write_text(text)
        for name in ("release_discovery.c", "updater.c"):
            output = self.work / (name + ".obj")
            subprocess.run([clang, "--target=i686-pc-windows-msvc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-nostdinc", "-I" + str(sdk), "-I" + str(self.work), "-I" + str(ROOT / "port/linux/src"),
                            "-DHALO_OG_RELEASE_DISCOVERY=1", '-DHALO_OG_SOURCE_REVISION="' + SHA + '"',
                            '-DHALO_OG_SOURCE_DATE="' + DATE + '"', "-c", str(ROOT / "port/linux/src" / name),
                            "-o", str(output)], check=True, capture_output=True, text=True)
            self.assertEqual(output.read_bytes()[:2], b"\x4c\x01")


class ReleaseIdentityTests(unittest.TestCase):
    def test_identity_is_commit_utc_and_discovery_only_clean_matching_fork_main(self):
        environment = {"GITHUB_REPOSITORY": identity.REPOSITORY, "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA}
        with patch.object(identity.subprocess, "check_output", side_effect=[SHA + "\n", "1791028800\n"]) as source, \
                patch.object(identity.subprocess, "run") as check:
            check.return_value.returncode = 0
            check.return_value.stdout = b""
            result = identity.ci_source_identity(environment)
        self.assertEqual(result, {"source_sha": SHA, "source_date": DATE})
        expected_git = ["git", "-c", f"safe.directory={identity.ROOT}"]
        self.assertEqual(source.call_args_list[0].args[0], [*expected_git, "rev-parse", "HEAD"])
        self.assertEqual(source.call_args_list[1].args[0], [*expected_git, "show", "-s", "--format=%ct", "HEAD"])
        self.assertEqual(check.call_args.args[0], [*expected_git, "status", "--porcelain", "--untracked-files=normal"])
        with patch.object(identity, "ci_source_identity", return_value=result):
            defines = identity.desktop_discovery_defines(environment)
        self.assertIn("-DHALO_OG_RELEASE_DISCOVERY=1", defines)
        self.assertIn(SHA, defines); self.assertIn(DATE, defines)
        for changes in ({"GITHUB_REPOSITORY": "cybersecurity/halo-ce-universal"}, {"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_SHA": OTHER}):
            with patch.object(identity, "source_identity", return_value=result):
                self.assertIsNone(identity.ci_source_identity(environment | changes))
        with patch.object(identity, "source_identity", return_value=result), patch.object(identity.subprocess, "run") as check:
            check.return_value.returncode = 1
            check.return_value.stdout = b""
            self.assertIsNone(identity.ci_source_identity(environment))
            check.return_value.returncode = 0
            check.return_value.stdout = b"?? untracked-source.c\n"
            self.assertIsNone(identity.ci_source_identity(environment))


if __name__ == "__main__": unittest.main()
