"""Authored release metadata, signed install records and native tests of the desktop notice."""
import base64
import copy
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_build, ed25519_verify as ed25519, release_discovery as identity

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


def sign(seed, message):
    """A test key's public half and its Ed25519 signature (RFC 8032), for fixture records."""
    def encode(point):
        inverse = pow(point[2], ed25519.P - 2, ed25519.P)
        x, y = point[0] * inverse % ed25519.P, point[1] * inverse % ed25519.P
        return (y | (x & 1) << 255).to_bytes(32, "little")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little") & ((1 << 254) - 8) | 1 << 254
    public = encode(ed25519._multiply(scalar, ed25519.BASE))
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % ed25519.ORDER
    commitment = encode(ed25519._multiply(nonce, ed25519.BASE))
    challenge = int.from_bytes(hashlib.sha512(commitment + public + message).digest(), "little") % ed25519.ORDER
    return public, commitment + ((nonce + challenge * scalar) % ed25519.ORDER).to_bytes(32, "little")


SEED = bytes(range(32))
PLATFORM = "windows" if sys.platform == "win32" else "linux"
TAG = "test-v0.3.0-net11-next"
NEWER = "2026-10-04T12:00:00Z"
DIGEST = hashlib.sha256(b"release zip").hexdigest()


def record(**changes):
    fields = {"platform": PLATFORM, "tag": TAG, "source": OTHER, "date": NEWER, "file": ASSET,
              "size": "13609682", "sha256": DIGEST} | changes
    return ("Halo OG update 1\n" + "".join(f"{name}: {value}\n" for name, value in fields.items())).encode()


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
#define SDL_MESSAGEBOX_ERROR 16
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
bool SDL_ShowSimpleMessageBox(unsigned,const char*,const char*,SDL_Window*);
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
/* The fixture's own key stands in for Halo OG's, whose private half is not here. */
#define HALO_UPDATE_KEY_H
static unsigned char halo_update_public_key[32];
#include "release_discovery.c"
#define FIXTURE_TAG "test-v0.3.0-net11-next"
#define FIXTURE_RECORD_URL "https://dl.oghalo.com/updates/" RELEASE_PLATFORM "/" FIXTURE_TAG ".txt"
static char fixture_path[1024], record_path[1024], signature_path[1024], opened[256], shown[800];
static int checks, dialogs, answer, writes, auto_check=1, hidden, fullscreen=1;
static int expect_install, installs, install_result, relaunches, errors;
static struct update_install_request installed;
static void unhex(const char *text,unsigned char *out,size_t count) {
    assert(strlen(text)==count*2);
    for(size_t i=0;i<count;i++) { unsigned value; assert(sscanf(text+i*2,"%2x",&value)==1); out[i]=(unsigned char)value; }
}
static char *load(const char *path,size_t *size) {
    FILE *f; char *data;
    f=fopen(path,"rb"); assert(f); fseek(f,0,SEEK_END); *size=(size_t)ftell(f); rewind(f);
    data=malloc(*size+1); assert(data); assert(fread(data,1,*size,f)==*size); data[*size]=0; fclose(f); return data;
}
int update_install_prepare(void) { return 1; }
int update_install(const struct update_install_request *request,char *error,size_t size) {
    installs++; installed=*request; assert(!strcmp(request->label,FIXTURE_TAG));
    if(!install_result) snprintf(error,size,"fixture failure");
    return install_result;
}
int update_install_relaunch(void) { relaunches++; return 0; }
bool SDL_ShowSimpleMessageBox(unsigned flags,const char *title,const char *message,SDL_Window *window) {
    assert(flags==SDL_MESSAGEBOX_ERROR && window); assert(!strcmp(title,"Halo OG update"));
    errors++; snprintf(shown,sizeof(shown),"%s",message); return true;
}
void platform_log(const char *fmt, ...) { (void)fmt; }
int config_boolean(const char *name) { return !strcmp(name,"update.auto") ? auto_check : hidden; }
double config_real(const char *name) { (void)name; return 0; }
const char *config_string(const char *name) { (void)name; return ""; }
int config_write_boolean(const char *name,int value) { assert(!strcmp(name,"update.auto")); writes++; auto_check=value; return 1; }
int update_make_private_temporary_directory(char *path,int capacity) { assert(capacity>32); strcpy(path,"fixture-temporary"); return 1; }
void update_delete_file(const char *path) {
    assert(!strcmp(path,"fixture-temporary/release-check.json") || !strcmp(path,"fixture-temporary") ||
        !strcmp(path,"fixture-temporary/install-record.txt") || !strcmp(path,"fixture-temporary/install-record.sig"));
}
int update_download_limited(const char *url,const char *path,unsigned long long bytes, update_progress_proc progress,void *context,char *error,int size) {
    assert(!progress && !context && error && size>0);
    /* The record and its signature are small, bounded, and fetched from the update host alone. */
    if(!strcmp(url,FIXTURE_RECORD_URL)) {
        assert(!strcmp(path,"fixture-temporary/install-record.txt") && bytes==HALO_RELEASE_INSTALL_RECORD_BYTES);
        return record_path[0]!=0;
    }
    if(!strcmp(url,FIXTURE_RECORD_URL ".sig")) {
        assert(!strcmp(path,"fixture-temporary/install-record.sig") && bytes==64);
        return signature_path[0]!=0;
    }
    assert(!strcmp(url,HALO_RELEASE_DISCOVERY_URL)); assert(!strcmp(path,"fixture-temporary/release-check.json"));
    assert(bytes==HALO_RELEASE_DISCOVERY_BYTES); checks++; return 1;
}
void *SDL_LoadFile(const char *path,size_t *size) {
    return load(strstr(path,"install-record.txt") ? record_path : strstr(path,"install-record.sig") ? signature_path : fixture_path,size);
}
SDL_Thread *SDL_CreateThread(int (*fn)(void*),const char *name,void *context) { static SDL_Thread thread; (void)name; fn(context); return &thread; }
void SDL_DetachThread(SDL_Thread *thread) { assert(thread); }
unsigned SDL_GetWindowFlags(SDL_Window *window) { assert(window); return fullscreen ? SDL_WINDOW_FULLSCREEN : 0; }
bool SDL_SetWindowFullscreen(SDL_Window *window,bool on) { assert(window); fullscreen=on; return true; }
bool SDL_ShowMessageBox(const SDL_MessageBoxData *box,int *chosen) {
    assert(!strcmp(box->title,"Halo OG update available"));
    if(expect_install) {
        assert(strstr(box->message,"Install it now") && box->numbuttons==4);
        assert(!strcmp(box->buttons[0].text,"Install update") && box->buttons[0].buttonID==3);
        assert(!strcmp(box->buttons[1].text,"Open download") && box->buttons[1].buttonID==1);
    } else {
        assert(strstr(box->message,"GitHub") && box->numbuttons==3);
        assert(!strcmp(box->buttons[0].text,"Open download"));
    }
    dialogs++; *chosen=answer; return true;
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
    if(!strcmp(argv[1],"record")) {
        /* record signature key asset tag source date */
        struct halo_release_install install; size_t record_size, signature_size; char *signature;
        assert(argc==10); unhex(argv[5],halo_update_public_key,32);
        data=load(argv[3],&record_size); signature=load(argv[4],&signature_size);
        memset(&notice,0,sizeof(notice));
        snprintf(notice.tag,sizeof(notice.tag),"%s",argv[7]); snprintf(notice.source_sha,sizeof(notice.source_sha),"%s",argv[8]);
        snprintf(notice.source_date,sizeof(notice.source_date),"%s",argv[9]);
        snprintf(notice.download_url,sizeof(notice.download_url),"https://github.com/pfista/halo-og/releases/download/%s/%s",argv[7],argv[6]);
        if(halo_release_install_parse(data,record_size,signature,signature_size,halo_update_public_key,argv[6],&notice,&install)) {
            printf("%s\n%llu\n",install.url,install.size);
            for(unsigned i=0;i<32;i++)printf("%02x",install.sha256[i]);
            printf("\n");
        }
        free(data); free(signature); return 0;
    }
    if(!strcmp(argv[1],"install") || !strcmp(argv[1],"install-fails") || !strcmp(argv[1],"unsigned")) {
        /* record signature key: a record the update host serves for the discovered release */
        assert(argc==6); snprintf(record_path,sizeof(record_path),"%s",argv[3]);
        snprintf(signature_path,sizeof(signature_path),"%s",argv[4]); unhex(argv[5],halo_update_public_key,32);
        expect_install=strcmp(argv[1],"unsigned")!=0; install_result=!strcmp(argv[1],"install");
        halo_release_discovery_start(); halo_release_discovery_set_main_menu(1);
        assert(release_state.value==release_available && release_installable==expect_install);
        answer=expect_install ? 3 : 1;
        halo_release_discovery_poll(&window); assert(dialogs==1 && fullscreen && installs==expect_install);
        if(!expect_install) { assert(opened[0] && !errors); return 0; }
        /* Only the file the signed record names is installed. */
        printf("%s\n%llu\n",installed.url,installed.size);
        assert(!memcmp(installed.sha256,release_install.sha256,32) && !opened[0] && errors==1);
        assert(relaunches==install_result);
        assert(strstr(shown,install_result ? "is installed, but could not be started" : "Your current version is unchanged"));
        if(!install_result) assert(strstr(shown,"fixture failure"));
        halo_release_discovery_poll(&window); assert(dialogs==1 && installs==1); return 0;
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

    def signed(self, data, signature=None):
        public, made = sign(SEED, data)
        (self.work / "record.txt").write_bytes(data)
        (self.work / "record.sig").write_bytes(made if signature is None else signature)
        return [str(self.work / "record.txt"), str(self.work / "record.sig"), public.hex()]

    def read_record(self, data, signature=None, key=None, asset=ASSET, tag=TAG, source=OTHER, date=NEWER):
        files = self.signed(data, signature)
        command = [str(self.binary), "record", "unused", files[0], files[1], key or files[2], asset, tag, source, date]
        return subprocess.check_output(command, text=True).splitlines()

    def test_signed_record_authorizes_exactly_the_discovered_release_file(self):
        url = f"https://github.com/pfista/halo-og/releases/download/{TAG}/{ASSET}"
        self.assertEqual(self.read_record(record()), [url, "13609682", DIGEST])
        # The release tool's verifier and the game's agree on the same signature.
        public, signature = sign(SEED, record())
        self.assertTrue(ed25519.verify(public, record(), signature))

    def test_a_record_not_signed_by_the_update_key_installs_nothing(self):
        _, signature = sign(SEED, record())
        other_key = sign(bytes(32), b"")[0].hex()
        for case in ({"signature": signature[:5] + bytes([signature[5] ^ 1]) + signature[6:]},
                     {"signature": signature[:-1]}, {"signature": bytes(64)}, {"key": other_key}):
            with self.subTest(case=list(case)): self.assertEqual(self.read_record(record(), **case), [])
        # A valid signature of other bytes: the record itself was changed after signing.
        self.assertEqual(self.read_record(record(sha256="0" * 64), signature=signature), [])

    def test_a_validly_signed_record_for_anything_else_installs_nothing(self):
        other_platform = "linux" if PLATFORM == "windows" else "windows"
        # Each record is properly signed, so only its contents are being judged.
        for changes in ({"tag": "v0.6.0"}, {"source": "c" * 40}, {"platform": other_platform},
                        {"file": f"halo-{other_platform}-release.zip"}, {"file": "halo.exe"},
                        # An older signed release cannot be replayed as the newer one.
                        {"date": "2026-10-01T12:00:00Z"},
                        {"size": "0"}, {"size": "013609682"}, {"size": "-1"}, {"size": "1e6"},
                        {"size": str(256 * 1024 * 1024 + 1)}, {"size": "9" * 15},
                        {"sha256": DIGEST.upper()}, {"sha256": DIGEST[:-1]}, {"sha256": DIGEST + "0"},
                        {"sha256": "g" * 64}, {"tag": TAG + " extra"}):
            with self.subTest(changes=changes): self.assertEqual(self.read_record(record(**changes)), [])
        valid = record()
        for data in (valid[:-1], valid + b"\n", valid + b"url: https://example.com/halo.zip\n",
                     valid.replace(b"\n", b"\r\n"), valid.replace(b"update 1", b"update 2"),
                     valid.replace(b"platform: ", b"Platform: "), b"\n".join(valid.split(b"\n")[1:]),
                     valid.replace(b"tag: " + TAG.encode() + b"\n", b""), valid + b" " * 512):
            with self.subTest(data=data[:60]): self.assertEqual(self.read_record(data), [])
        # The same record is refused for a release discovery did not select.
        for notice in ({"tag": "v0.6.0"}, {"source": "c" * 40}, {"date": "2026-10-05T12:00:00Z"},
                       {"asset": f"halo-{other_platform}-release.zip"}, {"asset": "Halo-OG-macos-arm64.dmg"}):
            with self.subTest(notice=notice): self.assertEqual(self.read_record(valid, **notice), [])

    def test_install_is_offered_only_for_a_signed_release_and_failure_keeps_playing(self):
        url = f"https://github.com/pfista/halo-og/releases/download/{TAG}/{ASSET}"
        metadata = self.work / "metadata.json"
        metadata.write_text(json.dumps([release()]))
        for mode in ("install", "install-fails"):
            with self.subTest(mode=mode):
                output = subprocess.check_output([str(self.binary), mode, str(metadata), *self.signed(record())], text=True)
                self.assertEqual(output.splitlines(), [url, "13609682"])
        _, signature = sign(SEED, record())
        for name, data, made in (("changed record", record(sha256="0" * 64), signature),
                                 ("another release", record(tag="v0.6.0"), None),
                                 ("older build", record(date="2026-10-01T12:00:00Z"), None)):
            with self.subTest(name=name):
                # Without a valid record the notice only opens the browser download.
                subprocess.run([str(self.binary), "unsigned", str(metadata), *self.signed(data, made)], check=True)

    def test_desktop_builds_carry_the_same_update_key_as_the_mac_app(self):
        header = (ROOT / "port/linux/src/halo_update_key.h").read_text()
        key = bytes(int(value, 16) for value in re.findall(r"0x([0-9a-f]{2})", header))
        settings = json.loads((ROOT / "port/macos/release-config.json").read_text())
        self.assertEqual(key, base64.b64decode(settings["public_update_key"]))

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

    def test_versioned_changelog_notes_are_readable_by_existing_clients(self):
        from tools.testing_release import release_notes
        record = {"repository": "pfista/halo-og", "tag": "v0.3.1", "sha": OTHER, "network_protocol": 11,
                  "overview": {"summary": "This release improves spawning and teleporter behavior during matches.",
                               "highlights": ["Fix spawning and teleporters",
                                              "Keep desktop update notices linked to the selected release"]},
                  "changelog": {"previous_tag": "test-v0.3.0-net11-setup2", "previous_sha": "c" * 40,
                                "commits": [{"sha": "d" * 40, "subject": "Fix spawning and teleporters"},
                                            {"sha": OTHER, "subject": f"Document https://github.com/pfista/halo-og/commit/{SHA})"}]}}
        for asset in (ASSET, "Halo-OG-macos-arm64.dmg"):
            with self.subTest(asset=asset):
                candidate = release(tag=record["tag"], asset=asset)
                candidate["body"] = release_notes(record)
                self.assertEqual(candidate["body"].count("https://github.com/pfista/halo-og/commit/"), 1)
                result = self.run_fixture("parse", [candidate], asset=asset)
                self.assertEqual(result[:2], ["v0.3.1", OTHER])

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
            "stdlib.h": "void free(void*);\n_Noreturn void exit(int);\n#define EXIT_SUCCESS 0\n",
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

    @unittest.skipUnless(shutil.which("git"), "git is required for the real CI source identity fixture")
    def test_restored_compile_cache_preserves_identity_but_dirty_source_does_not(self):
        with tempfile.TemporaryDirectory(prefix="halo-source-identity-") as directory:
            root = Path(directory).resolve()
            (root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
            source = root / "fixture-source.c"
            source.write_text("int fixture_source;\n")
            def git(*arguments):
                return subprocess.check_output(["git", "-C", str(root), *arguments], text=True, stderr=subprocess.PIPE).strip()
            git("-c", "init.defaultBranch=main", "init", "-q")
            git("add", ".gitignore", source.name)
            git("-c", "commit.gpgsign=false", "-c", "user.name=Halo fixture", "-c", "user.email=fixture@example.test",
                "commit", "-qm", "Authored source fixture")
            environment = {"GITHUB_REPOSITORY": identity.REPOSITORY, "GITHUB_REF": "refs/heads/main",
                           "GITHUB_SHA": git("rev-parse", "HEAD")}
            with patch.object(identity, "ROOT", root):
                clean = identity.required_ci_source_identity(environment)
                self.assertIsNotNone(clean)
                (root / ".ccache" / "cache-entry").mkdir(parents=True)
                (root / ".ccache/cache-entry/index").write_bytes(b"authored generated cache")
                self.assertEqual(identity.required_ci_source_identity(environment), clean)
                self.assertIn("-DHALO_OG_RELEASE_DISCOVERY=1", identity.desktop_discovery_defines(environment))
                source.write_text("int modified_source;\n")
                self.assertIsNone(identity.ci_source_identity(environment))
                with self.assertRaisesRegex(RuntimeError, "clean committed source tree"):
                    identity.desktop_discovery_defines(environment)
                source.write_text("int fixture_source;\n")
                (root / "untracked-source.c").write_text("int untracked_source;\n")
                with self.assertRaisesRegex(RuntimeError, "clean committed source tree"):
                    identity.required_ci_source_identity(environment)

    def test_source_identity_failure_is_required_only_for_halo_main_ci(self):
        environment = {"GITHUB_REPOSITORY": identity.REPOSITORY, "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA}
        with patch.object(identity, "ci_source_identity", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "cannot be disabled"):
                identity.required_ci_source_identity(environment)
            self.assertEqual(identity.desktop_discovery_defines({}), "-DHALO_OG_RELEASE_DISCOVERY=0")
            self.assertEqual(identity.desktop_discovery_defines(environment | {"GITHUB_REF": "refs/heads/feature"}),
                             "-DHALO_OG_RELEASE_DISCOVERY=0")

    def test_reconfigure_tracks_identity_helper_and_cache_ignore_rules(self):
        from tools import linux_build, windows_build
        for inputs in (linux_build.linux_configure_inputs(), windows_build.windows_configure_inputs()):
            self.assertIn(Path("tools/release_discovery.py"), inputs)
            self.assertIn(Path(".gitignore"), inputs)


class ReleaseArtifactIdentityTests(unittest.TestCase):
    @staticmethod
    def markers(platform):
        return [SHA, DATE, identity.DISCOVERY_URL, "Halo OG update available", "Open download",
                "Stop checking", "Install update", identity.DESKTOP_ASSETS[platform]]

    def test_collected_binary_requires_every_discovery_marker(self):
        with tempfile.TemporaryDirectory(prefix="halo-binary-markers-") as directory:
            binary = Path(directory) / "authored-binary"
            for platform in identity.DESKTOP_ASSETS:
                markers = self.markers(platform)
                binary.write_bytes("\0".join(markers).encode())
                identity.verify_desktop_discovery_artifact(binary, platform, {"source_sha": SHA, "source_date": DATE})
                for removed in markers:
                    with self.subTest(platform=platform, removed=removed):
                        binary.write_bytes("\0".join(value for value in markers if value != removed).encode())
                        with self.assertRaisesRegex(RuntimeError, "release discovery is missing"):
                            identity.verify_desktop_discovery_artifact(binary, platform, {"source_sha": SHA, "source_date": DATE})

    def test_ci_collection_verifies_binary_and_rejects_disabled_notice(self):
        for platform in identity.DESKTOP_ASSETS:
            for complete in (True, False):
                with self.subTest(platform=platform, complete=complete), tempfile.TemporaryDirectory(prefix="halo-ci-collect-") as directory:
                    root = Path(directory)
                    for output in ci_build.OUTPUTS[platform]:
                        path = root / output
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes("\0".join(self.markers(platform) if complete else [SHA, DATE]).encode())
                    for license in ("extract-xiso/LICENSE.TXT", "mbedtls/LICENSE", "miniupnpc/LICENSE"):
                        path = root / "port/third_party" / license
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("Authored license fixture")
                    notices = {
                        "port/assets/fonts/Overpass-OFL.txt": "Overpass-OFL.txt",
                        "port/assets/fonts/OpenCE-OFL.txt": "OpenCE-OFL.txt",
                        "port/assets/fonts/Newtown-LICENSE.txt": "Newtown-LICENSE.txt",
                        "port/assets/fonts/README.md": "fonts-README.md",
                        "port/third_party/stb/LICENSE": "stb-LICENSE.txt",
                    }
                    for source, name in notices.items():
                        notice = root / source
                        notice.parent.mkdir(parents=True, exist_ok=True)
                        notice.write_text("Authored notice fixture: " + name)
                    with patch.object(ci_build, "ROOT", root), patch.object(ci_build, "run") as run, \
                            patch.object(identity, "required_ci_source_identity", return_value={"source_sha": SHA, "source_date": DATE}), \
                            patch.object(sys, "argv", ["ci_build.py", platform, "release"]), \
                            patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
                        if complete:
                            self.assertEqual(ci_build.main(), 0)
                            self.assertIn("Verified Halo OG release discovery", output.getvalue())
                            for name in notices.values():
                                self.assertEqual((root / f"dist/halo-{platform}-release" / name).read_text(),
                                                 "Authored notice fixture: " + name)
                        else:
                            with self.assertRaisesRegex(RuntimeError, "release discovery is missing"):
                                ci_build.main()
                        self.assertEqual(run.call_args_list[-1].args[0], ["ninja", platform])
                        self.assertEqual(os.environ["HALO_BUILD_NUMBER"], "0")


if __name__ == "__main__": unittest.main()
