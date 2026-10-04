#!/usr/bin/env python3
"""Exercise package HTTPS delivery and native assembly in a synthetic private app.

The fixed compiled fixture helpers emit authored bytes. They are trusted only by
this isolated bundle's ContentTools.json; production code has no test hooks.
"""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import community_packages as packages


def fixture_map(name, kind=1):
    data = bytearray(4096)
    data[:4] = b"daeh"
    struct.pack_into("<II", data, 4, 5, 4096)
    struct.pack_into("<II", data, 16, 2048, 128)
    data[32:32 + len(name)] = name.encode()
    build = b"01.10.12.2276"
    data[64:64 + len(build)] = build
    struct.pack_into("<H", data, 96, kind)
    data[2044:2048] = b"toof"
    data[2048:] = bytes(i % 256 for i in range(2048, 4096))
    return bytes(data)


def synthetic_bundle(root):
    app = root / "Fixture.app"
    contents = app / "Contents"
    helpers, resources, macos = (contents / name for name in ("Helpers", "Resources", "MacOS"))
    for directory in (helpers, resources, macos):
        directory.mkdir(parents=True)
    (contents / "Info.plist").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleExecutable</key><string>map-downloads</string>
<key>CFBundleIdentifier</key><string>org.halo-og.tests.map-downloads</string>
<key>CFBundlePackageType</key><string>APPL</string></dict></plist>''')
    expected = root / "downrush.map"
    expected.write_bytes(fixture_map("downrush"))
    game = root / "game" / "maps"
    game.mkdir(parents=True)
    for name, kind in zip(packages.STOCK_NAMES, packages.STOCK_TYPES):
        (game / (name + ".map")).write_bytes(fixture_map(name, kind))
    # Both binaries accept only the argv used by the production assembler.
    extractor = root / "extract.c"
    extractor.write_text(r'''#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
 if(argc!=4 || strcmp(argv[1],"-t")) return 2;
 char path[4096]; if(snprintf(path,sizeof(path),"%s/original.weapon",argv[2])>=sizeof(path)) return 3;
 FILE *out=fopen(path,"wb"); if(!out) return 4;
 const char tag[]="AUTHORED-FIXTURE-STOCK-TAG";
 int ok=fwrite(tag,1,sizeof(tag)-1,out)==sizeof(tag)-1; return fclose(out)||!ok;
}''')
    builder = root / "build.c"
    encoded = ",".join(str(byte) for byte in expected.read_bytes())
    builder.write_text('''#include <stdio.h>\n#include <string.h>\n#include <unistd.h>\n'''
        + f"static const unsigned char cache[]={{ {encoded} }};\n"
        + r'''int main(int argc,char **argv) {
 if(argc!=15 || strcmp(argv[1],"-g") || strcmp(argv[2],"xbox-ntsc") || strcmp(argv[7],"-m") || strcmp(argv[13],"-E") || strcmp(argv[14],"levels/test/downrush/downrush")) return 2;
 char path[4096]; if(snprintf(path,sizeof(path),"%s/downrush.map",argv[8])>=sizeof(path)) return 3;
 FILE *out=fopen(path,"wb"); if(!out) return 4;
 usleep(500000); /* Authored fixture: expose cancellation during native assembly. */
 int ok=fwrite(cache,1,sizeof(cache),out)==sizeof(cache); return fclose(out)||!ok;
}''')
    pins = {}
    for name, source in (("extract", extractor), ("build", builder)):
        binary = helpers / ("invader-" + name)
        subprocess.run(["clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-O2", str(source), "-o", str(binary)], check=True)
        pins[name] = hashlib.sha256(binary.read_bytes()).hexdigest()
    record = {"schema": 1, "architecture": "arm64", "consumer_platform": "macos", "invader_commit": packages.INVADER_COMMIT,
        "binaries": {name: {"source_sha256": sha, "bundled_sha256": sha, "architecture": "arm64"} for name, sha in pins.items()}}
    (resources / "ContentTools.json").write_text(json.dumps(record))
    toolchain = root / "toolchain.json"
    toolchain.write_text(json.dumps({"invader_commit": packages.INVADER_COMMIT,
        "binaries": {name: {"sha256": sha} for name, sha in pins.items()}}))
    original, tags, data = (root / name for name in ("original-tags", "tags", "data"))
    for directory in (original, tags, data):
        directory.mkdir()
    (original / "original.weapon").write_bytes(b"AUTHORED-FIXTURE-STOCK-TAG")
    scenario = "levels/test/downrush/downrush"
    scenario_file = tags / (scenario + ".scenario")
    scenario_file.parent.mkdir(parents=True)
    scenario_file.write_bytes(b"AUTHORED-COMMUNITY-SCENARIO")
    packages.prepare_package(prepared_tags=tags, prepared_data=data, original_stock_tags=original,
        patched_stock_tags=original, stock_maps=game, expected_map=expected, scenario=scenario,
        toolchain_manifest=toolchain, destination=root / "downrush.hogpkg")
    raw = (root / "downrush.hogpkg").read_bytes()
    wrapped = struct.pack("<8sQ32s", b"HOGMAP2\n", len(raw), hashlib.sha256(raw).digest()) + zlib.compress(raw, 9)
    (root / "downrush.mapog").write_bytes(wrapped)
    malformed = {
        "trailing.mapog": wrapped + b"!",
        "truncated.mapog": wrapped[:-1],
        "wrong-sha.mapog": wrapped[:16] + bytes(32) + wrapped[48:],
        "overlimit.mapog": wrapped[:8] + struct.pack("<Q", (256 << 20) + 1) + wrapped[16:],
        "bomb.mapog": wrapped[:8] + struct.pack("<Q", 18) + wrapped[16:],
    }
    dictionary_stream = zlib.compressobj(zdict=b"AUTHORED-DICTIONARY")
    malformed["dictionary.mapog"] = wrapped[:48] + dictionary_stream.compress(raw) + dictionary_stream.flush()
    corrupted = bytearray(wrapped); corrupted[-2] ^= 1
    malformed["tampered.mapog"] = bytes(corrupted)
    for name, data in malformed.items():
        (root / name).write_bytes(data)
    return macos / "map-downloads"


def main():
    output = ROOT / "build/macos/tests/map-downloads"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fixtures-", dir=output) as directory:
        fixtures = Path(directory).resolve()
        executable = synthetic_bundle(fixtures)
        objects = []
        for source in (ROOT / "port/linux/src/community_mapog.c", ROOT / "port/third_party/miniz/tinfl_only.c"):
            target = fixtures / (source.stem + ".o")
            subprocess.run(["clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-O2",
                "-I", str(ROOT / "port/linux/src"), "-I", str(ROOT / "port/third_party/miniz"),
                "-c", str(source), "-o", str(target)], check=True)
            objects.append(str(target))
        subprocess.run([
            "clang", "-arch", "arm64", "-mmacosx-version-min=14.0", "-fobjc-arc", "-fblocks",
            "-O2", "-Wall", "-Wextra", "-Wno-deprecated-declarations", "-Iport/macos/native", "-Iport/linux/src",
            "port/macos/tests/map_downloads.m", "port/macos/native/HaloMapDownloads.m",
            "port/macos/native/HaloMapPackages.m", *objects, "-framework", "Foundation", "-o", str(executable),
        ], cwd=ROOT, check=True)
        subprocess.run([executable, fixtures, ROOT / "port/macos/map-downloads.json"], check=True, timeout=60)


if __name__ == "__main__":
    main()
