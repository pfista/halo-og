"""Build only pinned Invader extract/build helpers in a new private directory.

Developer/CI tool, never a game-side downloader. Source commits, dependency
archives and Cargo checksums are checked before compiling. Builds emit review
candidates; their hashes do not become application trust anchors automatically.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "tools/community-toolchain"
PINS = CONFIG / "pins.json"
MAX_ARCHIVE = 64 * 1024 * 1024
TOOLS = ("extract", "build")
OPTIONS = ("ARCHIVE", "BITMAP", "BLUDGEON", "BUILD", "COLLECTION", "COMPARE",
           "CONVERT", "CRC", "DEPENDENCY", "EDIT", "EDIT_QT", "EXTRACT", "FONT",
           "INDEX", "INFO", "LIGHTMAP", "MODEL", "RECOVER", "REFACTOR", "RESOURCE",
           "SCAN", "SCRIPT", "SOUND", "STRING", "STRIP")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def host_platform():
    system = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(platform.system())
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x86_64" if machine in ("amd64", "x86_64") else machine
    return f"{system}-{arch}"


def read_pins():
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    if sha256(CONFIG / "Cargo.lock") != pins["cargo_lock_sha256"]:
        raise RuntimeError("Reviewed Cargo.lock differs from its pin")
    return pins


def extract_archive(archive, destination, strip_root=True):
    """Reject links/special files and ambiguous names before any extraction."""
    destination = Path(destination)
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        seen, roots, files = set(), set(), set()
        total = 0
        for member in members:
            name = member.name.rstrip("/")
            components = name.split("/")
            if (not name or any(x in ("", ".", "..") for x in components)
                    or "\\" in name or ":" in name or name.startswith("/")
                    or not (member.isfile() or member.isdir())):
                raise RuntimeError("Unsafe corresponding-source archive entry")
            key = name.casefold()
            if key in seen:
                raise RuntimeError("Ambiguous corresponding-source archive entry")
            seen.add(key)
            roots.add(components[0])
            if member.isfile():
                files.add(key)
                total += member.size
                if member.size < 0 or total > 512 * 1024 * 1024:
                    raise RuntimeError("Corresponding-source archive exceeds its limit")
        if strip_root and len(roots) != 1:
            raise RuntimeError("Source archive must have exactly one root")
        for key in seen:
            if any("/".join(key.split("/")[:i]) in files for i in range(1, len(key.split("/")))):
                raise RuntimeError("Source archive contains a file/directory collision")
        destination.mkdir()
        for member in members:
            parts = member.name.rstrip("/").split("/")
            if strip_root:
                parts = parts[1:]
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def download_pinned(url, expected, destination, cache=None):
    destination = Path(destination)
    candidate = Path(cache) / destination.name if cache else None
    if candidate and candidate.is_file() and not candidate.is_symlink():
        shutil.copyfile(candidate, destination)
    else:
        if not url.startswith("https://"):
            raise RuntimeError("Source downloads require HTTPS")
        request = urllib.request.Request(url, headers={"User-Agent": "Halo-OG-source-builder/1"})
        with urllib.request.urlopen(request, timeout=60) as incoming, destination.open("xb") as outgoing:
            if not incoming.geturl().startswith("https://"):
                raise RuntimeError("Source download left HTTPS")
            total = 0
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                total += len(block)
                if total > MAX_ARCHIVE:
                    raise RuntimeError("Source archive exceeds download limit")
                outgoing.write(block)
    if destination.stat().st_size > MAX_ARCHIVE or sha256(destination) != expected:
        raise RuntimeError("Source archive differs from its checked-in SHA256: " + destination.name)


def git_source(repository, commit, directory, archive, cache, log, expected):
    """Archive a verified Git object, never local unstaged files or submodules."""
    cached_archive = Path(cache) / archive.name if cache else None
    if cached_archive and cached_archive.is_file() and not cached_archive.is_symlink():
        if sha256(cached_archive) != expected:
            raise RuntimeError("Git source archive differs from reviewed pin")
        shutil.copyfile(cached_archive, archive)
        extract_archive(archive, directory)
        return
    local = Path(cache) / directory.name if cache else None
    with tempfile.TemporaryDirectory(prefix=".git-source-", dir=archive.parent) as temporary:
        git_dir = local if local and (local / ".git").exists() else Path(temporary) / "source.git"
        if git_dir != local:
            subprocess.run(["git", "init", "--bare", str(git_dir)], check=True, stdout=log, stderr=log)
            subprocess.run(["git", "-C", str(git_dir), "fetch", "--depth=1", repository, commit], check=True, stdout=log, stderr=log)
        actual = subprocess.check_output(["git", "-C", str(git_dir), "rev-parse", commit + "^{commit}"], text=True).strip()
        if actual != commit:
            raise RuntimeError("Source Git object differs from the pinned commit")
        with archive.open("xb") as output:
            subprocess.run(["git", "-C", str(git_dir), "archive", "--format=tar", "--prefix=source/", commit], check=True, stdout=output, stderr=log)
    if sha256(archive) != expected:
        raise RuntimeError("Git source archive differs from reviewed pin")
    extract_archive(archive, directory)


def vendor_cargo(sources, archives, cache, pins):
    lock = tomllib.loads((CONFIG / "Cargo.lock").read_text(encoding="utf-8"))
    vendor = sources / "vendor"
    vendor.mkdir()
    for package in lock["package"]:
        if "source" not in package:
            continue
        if package["source"] != "registry+https://github.com/rust-lang/crates.io-index":
            raise RuntimeError("Unreviewed Cargo source")
        name = package["name"] + "-" + package["version"]
        archive = archives / (name + ".crate")
        crate_cache = Path(cache) if cache and (Path(cache) / archive.name).is_file() else Path(cache) / "cargo-home/registry/cache/index.crates.io-1949cf8c6b5b557f" if cache else None
        download_pinned("https://static.crates.io/crates/" + package["name"] + "/" + name + ".crate",
                        package["checksum"], archive, crate_cache)
        target = vendor / name
        extract_archive(archive, target)
        checksums = {str(path.relative_to(target)).replace(os.sep, "/"): sha256(path)
                     for path in sorted(target.rglob("*")) if path.is_file() and path.name != ".cargo-checksum.json"}
        (target / ".cargo-checksum.json").write_text(json.dumps({"files": checksums, "package": package["checksum"]}, sort_keys=True), encoding="utf-8")
    riat = sources / "invader/ext/riat"
    shutil.copyfile(CONFIG / "Cargo.lock", riat / "riatc/Cargo.lock")
    # Relative vendor location works when rebuilding the source archive elsewhere.
    config = riat / "riatc/.cargo"
    config.mkdir()
    (config / "config.toml").write_text('[source.crates-io]\nreplace-with = "reviewed-vendor"\n[source.reviewed-vendor]\ndirectory = "../../../../vendor"\n', encoding="utf-8")


def source_archive(sources, recipe_files, output, epoch, original_archives=None):
    """Stable source-only tar.gz; no build outputs, machine paths or game data."""
    paths = [(path, "source/" + path.relative_to(sources).as_posix())
             for path in sources.rglob("*") if path.is_file()]
    paths += [(Path(path), "source/recipe/" + name) for name, path in recipe_files.items()]
    if original_archives:
        paths += [(path, "source/archives/" + path.name) for path in Path(original_archives).iterdir() if path.is_file()]
    with Path(output).open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for path, name in sorted(paths, key=lambda item: item[1]):
                if path.is_symlink():
                    raise RuntimeError("Source delivery must not follow links")
                data = path.read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mtime = len(data), epoch
                info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                with io.BytesIO(data) as stream:
                    archive.addfile(info, stream)


def cmake_options(prefix, consumer, pins):
    options = ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_SHARED_LIBS=OFF",
               "-DCMAKE_POSITION_INDEPENDENT_CODE=ON", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
               "-DCMAKE_INSTALL_LIBDIR=lib", "-DCMAKE_INSTALL_PREFIX=" + str(prefix),
               "-DCMAKE_PREFIX_PATH=" + str(prefix), "-DBUILD_TESTING=OFF"]
    if consumer == "macos":
        options += ["-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=" + pins["macos_minimum"]]
    return options


def collect_notices(sources, rust_bin, output):
    mac = json.loads((CONFIG / "notices.json").read_text())
    output.mkdir()
    for name, relative in {**mac["notices"], "zlib.txt": "zlib-1.2.12/README"}.items():
        shutil.copyfile(sources / relative, output / name)
    for name, (relative, marker) in mac["header_notices"].items():
        text = (sources / relative).read_text(encoding="utf-8")
        offset = text.rfind(marker)
        if offset < 0:
            raise RuntimeError("Missing embedded dependency license")
        (output / name).write_text(text[offset:], encoding="utf-8")
    sysroot = Path(subprocess.check_output([str(rust_bin / "rustc"), "--print", "sysroot"], text=True).strip())
    docs = sysroot / "share/doc/rust"
    shutil.copyfile(docs / "COPYRIGHT-library.html", output / "Rust-COPYRIGHT-library.html")
    for name in mac["rust_notices"]:
        shutil.copyfile(docs / "licenses" / name, output / ("Rust-" + name))
    for crate in (sources / "vendor").iterdir():
        licenses = [path for path in crate.iterdir() if path.name.startswith(("LICENSE", "COPYING", "UNLICENSE")) and path.is_file()]
        if not licenses:
            raise RuntimeError("Cargo dependency license missing")
        for path in licenses:
            shutil.copyfile(path, output / (crate.name + "-" + path.name))
    shutil.copyfile(CONFIG / "dependencies.cmake", output / "invader-dependencies.cmake")
    shutil.copyfile(CONFIG / "README.md", output / "README.txt")
    return {path.name: sha256(path) for path in sorted(output.iterdir())}


def inspect_binary(binary, consumer):
    if consumer == "macos":
        from tools.macos_content_tools import _inspect
        libraries = _inspect(binary)
        lines = subprocess.check_output(["/usr/bin/otool", "-l", str(binary)], text=True)
        minimum = re.findall(r"\bminos\s+(\d+(?:\.\d+)+)", lines)
        if len(minimum) != 1 or tuple(map(int, minimum[0].split("."))) > (14, 0):
            raise RuntimeError("Native helper exceeds macOS 14 minimum")
        if any("libz." in library for library in libraries):
            raise RuntimeError("Native helper must use its pinned static zlib")
        return libraries, minimum[0]
    if consumer == "windows":
        header = subprocess.check_output(["objdump", "-f", str(binary)], text=True, encoding="utf-8", errors="replace")
        if "architecture: i386:x86-64" not in header:
            raise RuntimeError("Windows content helper must be native x86_64")
        text = subprocess.check_output(["objdump", "-p", str(binary)], text=True, encoding="utf-8", errors="replace")
        libraries = re.findall(r"DLL Name:\s*(\S+)", text)
        allowed = {"kernel32.dll", "msvcrt.dll", "userenv.dll", "ws2_32.dll", "advapi32.dll", "bcrypt.dll", "ntdll.dll", "synchronization.dll"}
        if not libraries or any(name.casefold() not in allowed for name in libraries):
            raise RuntimeError("Windows helper requires an unbundled non-system DLL: " + ", ".join(libraries))
        return libraries, "10.0"
    header = subprocess.check_output(["readelf", "-h", str(binary)], text=True, encoding="utf-8", errors="replace")
    if "Advanced Micro Devices X86-64" not in header:
        raise RuntimeError("Linux content helper must be native x86_64")
    text = subprocess.check_output(["readelf", "-d", str(binary)], text=True, encoding="utf-8", errors="replace")
    libraries = re.findall(r"Shared library: \[([^]]+)\]", text)
    allowed = {"libc.so.6", "libm.so.6", "libstdc++.so.6", "libgcc_s.so.1", "libpthread.so.0", "libdl.so.2", "librt.so.1", "libutil.so.1"}
    if not libraries or any(name not in allowed for name in libraries):
        raise RuntimeError("Linux helper requires an unbundled non-system library: " + ", ".join(libraries))
    return libraries, "ubuntu-24.04-build-host"


def build(output, source_cache=None, rust_bin=None, jobs=4):
    pins = read_pins()
    key = host_platform()
    if key not in pins["platforms"]:
        raise RuntimeError("No reviewed source recipe for this native platform: " + key)
    selected = pins["platforms"][key]
    consumer = selected["consumer_platform"]
    output = Path(output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # existing output is never changed
    sources, archives = output / "sources", output / "archives"
    sources.mkdir(); archives.mkdir()
    rust_bin = Path(rust_bin).resolve() if rust_bin else Path(shutil.which("cargo") or "").resolve().parent
    env = os.environ.copy()
    env["PATH"] = str(rust_bin) + os.pathsep + env["PATH"]
    env["CARGO_HOME"] = str(output / "cargo-home")
    env["CARGO_TARGET_DIR"] = str(output / "riat-build")
    env["SOURCE_DATE_EPOCH"] = str(pins["source_epoch"])
    env["MACOSX_DEPLOYMENT_TARGET"] = pins["macos_minimum"]
    env["RUSTFLAGS"] = "--remap-path-prefix=" + str(output) + "=/halo-content-tools"
    # Rust 1.95's implicit proc-macro debuginfo stripping can misalign Mach-O
    # LINKEDIT on newer dyld (rust-lang/rust#157750). Keep build-time metadata;
    # this changes neither RIAT's source nor the required macOS deployment target.
    env["CARGO_PROFILE_RELEASE_STRIP"] = "none"
    if consumer == "windows":
        compiler = subprocess.check_output(["gcc", "-v"], stderr=subprocess.STDOUT, text=True)
        if "msvcrt" not in compiler.lower() or "ucrt" in compiler.lower():
            raise RuntimeError("Windows recipe needs GNU/MSVCRT C++ matching the Rust windows-gnu target")
    versions = {}
    for name, command, expected in (("rust", [str(rust_bin / "rustc"), "--version"], pins["rust_version"]),
                                    ("cmake", ["cmake", "--version"], pins["cmake_version"]),
                                    ("ninja", ["ninja", "--version"], pins["ninja_version"])):
        result = subprocess.check_output(command, text=True, encoding="utf-8", errors="replace").splitlines()[0]
        if expected not in result.split() and not (name == "ninja" and result.startswith(expected + ".git.kitware.")):
            raise RuntimeError("Build requires pinned " + name + " " + expected + "; found " + result)
        versions[name] = result
    versions["cxx"] = subprocess.check_output(["c++", "--version"], text=True).splitlines()[0]
    with (output / "build.log").open("w", encoding="utf-8") as log:
        def run(command, cwd=None):
            subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=log, stderr=log, check=True)
        git_source(pins["invader_repository"], pins["invader_commit"], sources / "invader", archives / "invader.tar", source_cache, log, pins["invader_archive_sha256"])
        riat = sources / "invader/ext/riat"
        if riat.is_dir():
            riat.rmdir()
        riat_cache = Path(source_cache) / "invader/ext" if source_cache and (Path(source_cache) / "invader/ext").exists() else source_cache
        git_source(pins["riat_repository"], pins["riat_commit"], riat, archives / "riat.tar", riat_cache, log, pins["riat_archive_sha256"])
        for item in pins["archives"]:
            download_pinned(item["url"], item["sha256"], archives / item["file"], source_cache)
            extract_archive(archives / item["file"], sources / item["directory"], item.get("strip_root", True))
        # zlib 1.2.12 mistakes modern Apple's TargetConditionals macro for
        # classic Mac OS after newer SDK headers expose TARGET_OS_MAC. Limit
        # that obsolete fdopen fallback to classic Mac; compression is unchanged.
        zutil = sources / "zlib-1.2.12/zutil.h"
        text = zutil.read_text(encoding="utf-8")
        old = "#if defined(MACOS) || defined(TARGET_OS_MAC)"
        if text.count(old) != 1:
            raise RuntimeError("Reviewed zlib platform compatibility patch no longer applies")
        zutil.write_text(text.replace(old, "#if (defined(MACOS) || defined(TARGET_OS_MAC)) && !defined(__APPLE__)"), encoding="utf-8")
        vendor_cargo(sources, archives, source_cache, pins)
        shutil.copyfile(CONFIG / "dependencies.cmake", sources / "invader/dependencies.cmake")
        prefix = output / "prefix"
        base = cmake_options(prefix, consumer, pins)
        extras = {"libsamplerate": ["-DLIBSAMPLERATE_EXAMPLES=OFF"],
                  "libsquish": ["-DBUILD_SQUISH_WITH_SSE2=OFF", "-DBUILD_SQUISH_WITH_ALTIVEC=OFF", "-DBUILD_SQUISH_WITH_OPENMP=OFF", "-DBUILD_SQUISH_EXTRA=OFF"],
                  "flac": ["-DBUILD_CXXLIBS=OFF", "-DBUILD_PROGRAMS=OFF", "-DBUILD_EXAMPLES=OFF", "-DBUILD_DOCS=OFF", "-DINSTALL_MANPAGES=OFF"]}
        for item in pins["archives"]:
            directory = sources / item["directory"]
            target = output / ("build-" + item["name"])
            run(["cmake", "-S", directory, "-B", target, *base, *extras.get(item["name"], [])])
            if item["name"] == "zlib":
                run(["cmake", "--build", target, "--target", "zlibstatic", "-j", str(jobs)])
                (prefix / "lib").mkdir(parents=True, exist_ok=True)
                (prefix / "include").mkdir(exist_ok=True)
                candidates = [path for path in target.rglob("*.a") if path.name in ("libz.a", "libzlibstatic.a")]
                if len(candidates) != 1:
                    raise RuntimeError("Pinned static zlib output is missing or ambiguous")
                shutil.copyfile(candidates[0], prefix / "lib/libz.a")
                shutil.copyfile(directory / "zlib.h", prefix / "include/zlib.h")
                shutil.copyfile(target / "zconf.h", prefix / "include/zconf.h")
            else:
                run(["cmake", "--build", target, "-j", str(jobs)])
                run(["cmake", "--install", target])
            print("Built pinned dependency " + item["name"], flush=True)
        run([rust_bin / "cargo", "build", "--release", "--locked", "--offline", "--target", selected["rust_target"]], cwd=riat / "riatc")
        riat_library = output / "riat-build" / selected["rust_target"] / "release/libriatc.a"
        linker = "-framework Security -framework CoreFoundation -liconv" if consumer == "macos" else "-static" if consumer == "windows" else ""
        options = ["-DINVADER_" + option + ("=ON" if option in ("EXTRACT", "BUILD") else "=OFF") for option in OPTIONS]
        run(["cmake", "-S", sources / "invader", "-B", output / "build", *base,
             "-DPython3_EXECUTABLE=" + sys.executable, "-DHALO_CONTENT_PREFIX=" + str(prefix),
             "-DINVADER_RIATC_STATIC_LIBRARY=" + str(riat_library), "-DCMAKE_EXE_LINKER_FLAGS=" + linker,
             *options])
        run(["cmake", "--build", output / "build", "--target", "invader-extract", "invader-build", "-j", str(jobs)])
    return finalize_toolchain(output, rust_bin)


def finalize_toolchain(output, rust_bin):
    """Create provenance/source delivery after a successful private native build.

    This also supports finishing the builder's own interrupted candidate. It
    never replaces an existing manifest/source delivery or invokes game code.
    """
    pins = read_pins()
    selected = pins["platforms"][host_platform()]
    consumer = selected["consumer_platform"]
    output, rust_bin = Path(output).resolve(), Path(rust_bin).resolve()
    sources, archives = output / "sources", output / "archives"
    if any((output / name).exists() for name in ("source-manifest.json", "halo-content-tools-source.tar.gz", "Licenses")):
        raise FileExistsError("Finalized helper provenance already exists")
    versions = {}
    for name, command in (("rust", [str(rust_bin / "rustc"), "--version"]),
                          ("cmake", ["cmake", "--version"]), ("ninja", ["ninja", "--version"]),
                          ("cxx", ["c++", "--version"])):
        versions[name] = subprocess.check_output(command, text=True).splitlines()[0]
    if consumer == "macos":
        versions["sdk"] = subprocess.check_output(["/usr/bin/xcrun", "--sdk", "macosx", "--show-sdk-version"], text=True).strip()
    versions["build_host"] = platform.system() + " " + platform.release()
    binaries = {}
    for name in TOOLS:
        path = output / "build" / ("invader-" + name + (".exe" if consumer == "windows" else ""))
        libraries, minimum = inspect_binary(path, consumer)
        subprocess.run([str(path), "--info"], check=True, capture_output=True)
        binaries[name] = {"sha256": sha256(path), "architecture": selected["architecture"], "system_libraries": libraries, "minimum_system": minimum}
    notices = collect_notices(sources, rust_bin, output / "Licenses")
    archive_name = "halo-content-tools-source.tar.gz"
    # Binary/ delivery hashes are review outputs, never source-build inputs.
    # Omitting them from the delivered recipe avoids a source-archive self-hash.
    recipe_pins = json.loads(json.dumps(pins))
    for item in recipe_pins["platforms"].values():
        item["binaries"] = {}
        item.pop("corresponding_source_sha256", None)
        item.pop("license_manifest_sha256", None)
    delivered_pins = output / "recipe-source-pins.json"
    delivered_pins.write_text(json.dumps(recipe_pins, indent=2) + "\n", encoding="utf-8")
    source_archive(sources, {"tools/community_toolchain.py": __file__, "tools/macos_content_tools.py": ROOT / "tools/macos_content_tools.py", "tools/community-toolchain/pins.json": delivered_pins,
                            "tools/community-toolchain/Cargo.lock": CONFIG / "Cargo.lock", "tools/community-toolchain/dependencies.cmake": CONFIG / "dependencies.cmake",
                            "tools/community-toolchain/notices.json": CONFIG / "notices.json",
                            "tools/community-toolchain/.gitattributes": CONFIG / ".gitattributes",
                            "tools/community-toolchain/README.md": CONFIG / "README.md"}, output / archive_name, pins["source_epoch"], archives)
    manifest = {key: pins[key] for key in ("schema", "invader_repository", "invader_commit", "riat_repository", "riat_commit", "rust_version")}
    manifest.update({"consumer_platform": consumer, "architecture": selected["architecture"], "build_versions": versions,
                     "compatible_package_producers": pins["compatible_package_producers"], "binaries": binaries,
                     "fresh_ci_ready": False, "notices_sha256": notices,
                     "corresponding_source": {"file": archive_name, "size": (output / archive_name).stat().st_size, "sha256": sha256(output / archive_name)}})
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Review candidate " + str(output / "source-manifest.json"), flush=True)
    return manifest


def stage_desktop_content_tools(destination, toolchain_directory):
    """Package independently reviewed native hashes beside a desktop game.

    Output's fixed layout is content-tools/{helpers,ContentTools.json,Licenses,
    source archive}. Never use a downloaded package as an executable trust root.
    """
    pins = read_pins()
    key = host_platform()
    selected = pins["platforms"].get(key)
    if not selected or set(selected["binaries"]) != set(TOOLS):
        raise RuntimeError("Native platform binary hashes have not been reviewed")
    directory = Path(toolchain_directory).resolve(strict=True)
    manifest = json.loads((directory / "source-manifest.json").read_text(encoding="utf-8"))
    for field in ("invader_commit", "riat_commit", "rust_version", "compatible_package_producers"):
        if manifest.get(field) != pins[field]:
            raise RuntimeError("Native helper manifest differs from trusted " + field)
    if (manifest.get("consumer_platform") != selected["consumer_platform"]
            or manifest.get("architecture") != selected["architecture"]):
        raise RuntimeError("Native helper manifest has wrong platform")
    source = manifest.get("corresponding_source", {})
    if (source.get("file") != "halo-content-tools-source.tar.gz" or isinstance(source.get("size"), bool)
            or not isinstance(source.get("size"), int)
            or source.get("sha256") != selected.get("corresponding_source_sha256")):
        raise RuntimeError("Corresponding source record is missing")
    archive = directory / source["file"]
    if archive.is_symlink() or archive.stat().st_size != source["size"] or sha256(archive) != source.get("sha256"):
        raise RuntimeError("Corresponding source differs from provenance")
    expected_notices = manifest.get("notices_sha256", {})
    if (not isinstance(expected_notices, dict) or not expected_notices
            or hashlib.sha256(json.dumps(expected_notices, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != selected.get("license_manifest_sha256")
            or {x.name for x in (directory / "Licenses").iterdir()} != set(expected_notices)):
        raise RuntimeError("Native helper licenses are incomplete")
    for name, expected in expected_notices.items():
        path = directory / "Licenses" / name
        if Path(name).name != name or path.is_symlink() or not path.is_file() or sha256(path) != expected:
            raise RuntimeError("Native helper license differs from provenance")
    records = {}
    for name, expected in selected["binaries"].items():
        path = directory / "build" / ("invader-" + name + (".exe" if selected["consumer_platform"] == "windows" else ""))
        if path.is_symlink() or not path.is_file() or sha256(path) != expected or manifest.get("binaries", {}).get(name, {}).get("sha256") != expected:
            raise RuntimeError("Native helper differs from checked-in binary pin")
        libraries, _ = inspect_binary(path, selected["consumer_platform"])
        records[name] = {"source_sha256": expected, "bundled_sha256": expected,
                         "architecture": selected["architecture"], "system_libraries": libraries}
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Native helper destination already exists")
    destination.mkdir()
    try:
        for name in TOOLS:
            filename = "invader-" + name + (".exe" if selected["consumer_platform"] == "windows" else "")
            shutil.copyfile(directory / "build" / filename, destination / filename)
            (destination / filename).chmod(0o755)
        shutil.copytree(directory / "Licenses", destination / "Licenses")
        shutil.copyfile(archive, destination / source["file"])
        record = {key: manifest[key] for key in ("schema", "invader_repository", "invader_commit", "riat_repository", "riat_commit", "rust_version", "consumer_platform", "architecture", "compatible_package_producers", "corresponding_source", "notices_sha256", "fresh_ci_ready")}
        record["binaries"] = records
        (destination / "ContentTools.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-cache", type=Path, help="Optional existing reviewed source/archive cache; never modified")
    parser.add_argument("--rust-bin", type=Path, help="Pinned Rust compiler's bin directory")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--finalize-existing", action="store_true", help="Finish this recipe's interrupted build before provenance was created")
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error("--jobs must be 1..32")
    if args.finalize_existing:
        if not args.rust_bin:
            parser.error("--finalize-existing requires --rust-bin")
        finalize_toolchain(args.output, args.rust_bin)
    else:
        build(args.output, args.source_cache, args.rust_bin, args.jobs)


if __name__ == "__main__":
    main()
