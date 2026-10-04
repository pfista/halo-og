"""Package or fetch independently reviewed native reconstruction helpers.

Only this repository's fixed GitHub release assets are fetched. Archive and
per-file pins are independent of the downloaded manifest. No helper executes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile

from tools import community_toolchain

ROOT = Path(__file__).resolve().parents[1]
DISTRIBUTION = ROOT / "tools/community-toolchain/distribution.json"
CACHE = ROOT / "build/community-tools/downloads"
RELEASE = "https://github.com/pfista/halo-og/releases/download/content-tools-v1/"
REDIRECT_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
MAX_ZIP_BYTES = 192 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_NOTICE_BYTES = 16 * 1024 * 1024
SOURCE = "halo-content-tools-source.tar.gz"
TOOLS = ("extract", "build")


def _unsafe(info):
    return (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _directory(path):
    info = Path(path).lstat()
    if _unsafe(info) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("Helper directory must not be a link or special file")


def _read(path, limit):
    path = Path(path)
    before = path.lstat()
    if _unsafe(before) or not stat.S_ISREG(before.st_mode) or before.st_size > limit:
        raise RuntimeError("Helper input must be a bounded regular file: " + path.name)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (_unsafe(info) or not stat.S_ISREG(info.st_mode) or
                (info.st_dev, info.st_ino) != (before.st_dev, before.st_ino)):
            raise RuntimeError("Helper input changed while opening")
        data = stream.read(limit + 1)
        if len(data) != before.st_size or len(data) > limit:
            raise RuntimeError("Helper input changed or exceeds its limit")
    return data


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RuntimeError("Duplicate helper manifest key")
            result[key] = value
        return result
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeError, ValueError) as error:
        raise RuntimeError("Invalid helper JSON") from error


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _name(name):
    if (not isinstance(name, str) or not name or any(x in name for x in '/\\:<>"|?*~')
            or name[-1] in ". " or any(ord(x) < 32 for x in name)
            or name in (".", "..")
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0])):
        raise RuntimeError("Unsafe helper file name")
    return name


def _trusted(platform_key):
    pins = community_toolchain.read_pins()
    selected = pins["platforms"].get(platform_key)
    if (not selected or set(selected.get("binaries", {})) != set(TOOLS)
            or not selected.get("corresponding_source_sha256") or not selected.get("license_manifest_sha256")):
        raise RuntimeError("Native helper platform has not been independently reviewed")
    return pins, selected


def _inventory(manifest, platform_key):
    pins, selected = _trusted(platform_key)
    if not isinstance(manifest, dict) or type(manifest.get("schema")) is not int or manifest["schema"] != 1:
        raise RuntimeError("Unsupported helper manifest")
    for field in ("invader_repository", "invader_commit", "riat_repository", "riat_commit",
                  "rust_version", "compatible_package_producers"):
        if manifest.get(field) != pins[field]:
            raise RuntimeError("Helper provenance differs from checked-in " + field)
    if (manifest.get("consumer_platform") != selected["consumer_platform"] or
            manifest.get("architecture") != selected["architecture"]):
        raise RuntimeError("Helper manifest platform differs from checked-in pins")
    source = manifest.get("corresponding_source", {})
    if (not isinstance(source, dict) or source.get("file") != SOURCE
            or type(source.get("size")) is not int or not 0 < source["size"] <= MAX_FILE_BYTES
            or source.get("sha256") != selected["corresponding_source_sha256"]):
        raise RuntimeError("Helper corresponding source is not independently pinned")
    notices = manifest.get("notices_sha256")
    if (not isinstance(notices, dict) or not notices or len(notices) > 250
            or _digest(json.dumps(notices, sort_keys=True, separators=(",", ":")).encode()) != selected["license_manifest_sha256"]):
        raise RuntimeError("Helper license inventory is not independently pinned")
    inventory = {SOURCE: (source["sha256"], MAX_FILE_BYTES)}
    folded = set()
    for name, digest in notices.items():
        _name(name)
        if name.casefold() in folded or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("Ambiguous helper license inventory")
        folded.add(name.casefold())
        inventory["Licenses/" + name] = (digest, MAX_NOTICE_BYTES)
    binaries = manifest.get("binaries", {})
    if not isinstance(binaries, dict) or set(binaries) != set(TOOLS):
        raise RuntimeError("Helper binary inventory is incomplete")
    for name in TOOLS:
        if (not isinstance(binaries[name], dict) or binaries[name].get("sha256") != selected["binaries"][name]
                or binaries[name].get("architecture") != selected["architecture"]):
            raise RuntimeError("Helper binary differs from independent platform pin")
        suffix = ".exe" if selected["consumer_platform"] == "windows" else ""
        inventory["build/invader-" + name + suffix] = (selected["binaries"][name], MAX_FILE_BYTES)
    return inventory


def validate_content_tools(directory, platform_key, exact=False):
    """Read hashes only; no supplied helper or inspection executable runs."""
    directory = Path(directory)
    _directory(directory)
    for name in ("build", "Licenses"):
        _directory(directory / name)
    manifest = _json(_read(directory / "source-manifest.json", MAX_MANIFEST_BYTES))
    inventory = _inventory(manifest, platform_key)
    if {x.name for x in (directory / "Licenses").iterdir()} != set(manifest["notices_sha256"]):
        raise RuntimeError("Helper license directory has unknown or missing files")
    if exact:
        expected = set(inventory) | {"source-manifest.json", "build", "Licenses"}
        found = set()
        for path in directory.rglob("*"):
            info = path.lstat()
            if _unsafe(info) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise RuntimeError("Unsafe extracted helper file")
            found.add(path.relative_to(directory).as_posix())
        if found != expected:
            raise RuntimeError("Extracted helper directory has unknown or missing files")
    total = 0
    for name, (digest, limit) in inventory.items():
        data = _read(directory / name, limit)
        total += len(data)
        if total > MAX_EXPANDED_BYTES or _digest(data) != digest:
            raise RuntimeError("Helper bytes differ from independently reviewed pins")
        if name == SOURCE and len(data) != manifest["corresponding_source"]["size"]:
            raise RuntimeError("Helper corresponding source size differs")
    return manifest, inventory


def archive_content_tools(platform_key, toolchain_directory, output):
    """Write a fixed-layout ZIP exclusively from already-reviewed local bytes."""
    directory, output = Path(toolchain_directory), Path(output)
    _, inventory = validate_content_tools(directory, platform_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".content-tools-archive-", dir=output.parent) as private:
        candidate = Path(private) / "candidate.zip"
        with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(set(inventory) | {"source-manifest.json"}):
                limit = inventory[name][1] if name in inventory else MAX_MANIFEST_BYTES
                data = _read(directory / name, limit)
                if name in inventory and _digest(data) != inventory[name][0]:
                    raise RuntimeError("Helper input changed while packaging")
                item = zipfile.ZipInfo(name, (2026, 4, 1, 0, 0, 0))
                item.create_system = 3
                mode = 0o755 if name.startswith("build/") else 0o644
                item.external_attr = (stat.S_IFREG | mode) << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(item, data, compresslevel=9)
        if candidate.stat().st_size > MAX_ZIP_BYTES:
            raise RuntimeError("Helper ZIP exceeds its byte limit")
        _validate_zip(candidate, platform_key)
        digest = _digest(_read(candidate, MAX_ZIP_BYTES))
        os.link(candidate, output)  # never replace an existing or raced output
        return {"url": RELEASE + "content-tools-" + platform_key + ".zip",
                "sha256": digest, "size": output.stat().st_size}


def _validate_zip(path, platform_key):
    with zipfile.ZipFile(path) as archive:
        entries, total = {}, 0
        for item in archive.infolist():
            name = item.filename
            components = name.rstrip("/").split("/")
            if (name != item.orig_filename or name.startswith("/") or any(not x for x in components)
                    or len(components) > 2 or item.flag_bits & 1
                    or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise RuntimeError("Unsafe helper ZIP entry")
            for component in components:
                _name(component)
            mode = item.external_attr >> 16
            if ((item.is_dir() and (name not in ("build/", "Licenses/") or stat.S_IFMT(mode) not in (0, stat.S_IFDIR)))
                    or (not item.is_dir() and stat.S_IFMT(mode) not in (0, stat.S_IFREG))):
                raise RuntimeError("Helper ZIP contains a link or special file")
            key = name.rstrip("/").casefold()
            if key in entries or item.file_size < 0 or item.file_size > MAX_FILE_BYTES:
                raise RuntimeError("Ambiguous or oversized helper ZIP entry")
            entries[key] = item
            total += item.file_size
            if len(entries) > 256 or total > MAX_EXPANDED_BYTES:
                raise RuntimeError("Helper ZIP exceeds expansion limits")
        record = entries.get("source-manifest.json")
        if not record or record.filename != "source-manifest.json" or record.file_size > MAX_MANIFEST_BYTES:
            raise RuntimeError("Helper ZIP manifest is missing or oversized")
        manifest = _json(archive.read(record))
        inventory = _inventory(manifest, platform_key)
        actual = {item.filename for item in entries.values() if not item.is_dir()}
        if actual != set(inventory) | {"source-manifest.json"}:
            raise RuntimeError("Helper ZIP has unknown or missing files")
        for name, (_, limit) in inventory.items():
            if archive.getinfo(name).file_size > limit:
                raise RuntimeError("Helper ZIP file exceeds its byte limit")
        return inventory


def _extract_zip(path, destination, platform_key):
    inventory = _validate_zip(path, platform_key)
    destination = Path(destination)
    destination.mkdir()
    (destination / "build").mkdir(); (destination / "Licenses").mkdir()
    with zipfile.ZipFile(path) as archive:
        for name in sorted(set(inventory) | {"source-manifest.json"}):
            limit = inventory[name][1] if name in inventory else MAX_MANIFEST_BYTES
            with archive.open(name) as source, (destination / name).open("xb") as target:
                written = 0
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    written += len(block)
                    if written > limit:
                        raise RuntimeError("Helper ZIP expansion exceeds file limit")
                    target.write(block)
            (destination / name).chmod(0o755 if name.startswith("build/") else 0o644)
    validate_content_tools(destination, platform_key, exact=True)


def _https(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise RuntimeError("Invalid helper HTTPS URL") from None
    if (parsed.scheme != "https" or parsed.hostname not in REDIRECT_HOSTS
            or parsed.username is not None or parsed.password is not None or port not in (None, 443)
            or parsed.fragment):
        raise RuntimeError("Helper download redirect is outside approved HTTPS hosts")


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 1

    def redirect_request(self, request, response, code, message, headers, new_url):
        _https(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def _download(record, destination):
    try:
        _download_checked(record, destination)
    except OSError:
        # HTTP exceptions can include signed CDN query strings; do not log them.
        raise RuntimeError("Helper HTTPS download failed") from None


def _download_checked(record, destination):
    _https(record["url"])
    request = urllib.request.Request(record["url"], headers={"Accept-Encoding": "identity", "User-Agent": "Halo-OG-content-tools/1"})
    opener = urllib.request.build_opener(_Redirects())
    response = opener.open(request, timeout=60)
    with response, Path(destination).open("xb") as output:
        _https(response.geturl())
        if response.status != 200 or response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise RuntimeError("Helper download must be an unencoded HTTP 200 response")
        length = response.headers.get("Content-Length")
        if length is not None and (len(length) > 20 or not re.fullmatch(r"[0-9]+", length) or int(length) != record["size"]):
            raise RuntimeError("Helper download Content-Length differs from checked-in size")
        count, digest = 0, hashlib.sha256()
        for block in iter(lambda: response.read(1024 * 1024), b""):
            count += len(block)
            if count > record["size"]:
                raise RuntimeError("Helper download exceeds checked-in size")
            digest.update(block); output.write(block)
        if count != record["size"] or digest.hexdigest() != record["sha256"]:
            raise RuntimeError("Helper download differs from checked-in ZIP hash or size")


def _distribution(platform_key):
    _trusted(platform_key)
    config = _json(_read(DISTRIBUTION, MAX_MANIFEST_BYTES))
    if not isinstance(config, dict) or not isinstance(config.get("platforms"), dict):
        raise RuntimeError("Invalid checked-in helper release configuration")
    record = config.get("platforms", {}).get(platform_key)
    expected_url = RELEASE + "content-tools-" + platform_key + ".zip"
    if (config.get("schema") != 1 or not isinstance(record, dict) or record.get("url") != expected_url
            or not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
            or type(record.get("size")) is not int or not 0 < record["size"] <= MAX_ZIP_BYTES):
        raise RuntimeError("Helper release archive has not been independently reviewed")
    return record


def _cache_parent(path):
    path = Path(path).absolute()
    missing = []
    current = path
    while not current.exists() and not current.is_symlink():
        missing.append(current); current = current.parent
    for ancestor in (current, *current.parents):
        _directory(ancestor)
    for directory in reversed(missing):
        try:
            directory.mkdir()
        except FileExistsError:
            pass
        _directory(directory)


def fetch_content_tools(platform_key):
    """Return a hash-validated private build cache; never run fetched helpers."""
    record = _distribution(platform_key)
    parent = CACHE / platform_key
    _cache_parent(parent)
    destination = parent / record["sha256"]
    if destination.exists() or destination.is_symlink():
        validate_content_tools(destination, platform_key, exact=True)
        return destination
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=parent) as private:
        private = Path(private)
        archive = private / "helpers.zip"
        _download(record, archive)
        prepared = private / "verified"
        _extract_zip(archive, prepared, platform_key)
        # mkdir/copytree's exclusive leaf never replaces a concurrent cache.
        owned = False
        try:
            destination.mkdir(); owned = True
            for name in ("build", "Licenses"):
                shutil.copytree(prepared / name, destination / name)
            for name in ("source-manifest.json", SOURCE):
                with (prepared / name).open("rb") as source, (destination / name).open("xb") as target:
                    shutil.copyfileobj(source, target)
            validate_content_tools(destination, platform_key, exact=True)
        except FileExistsError:
            if owned:
                shutil.rmtree(destination)
                raise
            validate_content_tools(destination, platform_key, exact=True)
        except BaseException:
            if owned:
                shutil.rmtree(destination)
            raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch"); fetch.add_argument("--platform", required=True)
    archive = commands.add_parser("archive"); archive.add_argument("--platform", required=True)
    archive.add_argument("--toolchain", required=True, type=Path)
    archive.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "fetch":
        print(fetch_content_tools(args.platform))
    else:
        print(json.dumps(archive_content_tools(args.platform, args.toolchain, args.output), indent=2))


if __name__ == "__main__":
    main()
