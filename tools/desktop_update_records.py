"""Signed install records that let Windows and Linux builds install a release.

A desktop build installs the release it discovers only when the update host
serves a record for that tag and platform, signed by Halo OG's update key. The
record names the release's zip by size and SHA-256; the zip itself stays on the
GitHub release. port/linux/src/release_discovery.c reads the record, and
tools/test_release_discovery.py checks both sides agree on its format.
"""
import hashlib
import io
import re
import zipfile

PLATFORMS = {"windows": "halo-windows-release.zip", "linux": "halo-linux-release.zip"}
EXECUTABLES = {"windows": {"halo.exe", "SDL3.dll"}, "linux": {"halo"}}
MAXIMUM_BYTES = 256 * 1024 * 1024
MAXIMUM_FILES = 32


def record(platform, tag, source, date, size, sha256):
    """The exact bytes that are signed and that the game parses."""
    file = PLATFORMS[platform]
    if (not re.fullmatch(r"v\d+\.\d+\.\d+", tag) or not re.fullmatch(r"[0-9a-f]{40}", source)
            or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", date) or not 0 < size <= MAXIMUM_BYTES
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)):
        raise RuntimeError("An install record needs a release tag, source commit, release date, size and SHA-256")
    return (f"Halo OG update 1\nplatform: {platform}\ntag: {tag}\nsource: {source}\ndate: {date}\n"
            f"file: {file}\nsize: {size}\nsha256: {sha256}\n").encode("ascii")


def audit_package(platform, data):
    """Refuse a zip the game's installer would only partly install."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if archive.testzip() is not None:
            raise RuntimeError(f"The {platform} package is corrupt")
        methods = {entry.compress_type for entry in archive.infolist()}
    if (len(names) > MAXIMUM_FILES or len(set(names)) != len(names) or "config.toml" in names
            or any("/" in name or "\\" in name or ":" in name or name in (".", "..") for name in names)):
        raise RuntimeError(f"The {platform} package must hold at most {MAXIMUM_FILES} files at its top level and no settings")
    if not EXECUTABLES[platform] <= set(names):
        raise RuntimeError(f"The {platform} package is missing its executable")
    if not methods <= {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise RuntimeError(f"The {platform} package uses a compression the game cannot unpack")


def keys(platform, tag):
    """The update host's object keys of a record and its signature."""
    if platform not in PLATFORMS or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise RuntimeError("Install records are published per platform and release tag")
    key = f"updates/{platform}/{tag}.txt"
    return key, key + ".sig"


def upload(platform, tag, data, signature, origin, r2, fetch):
    """Create a release's record and signature, which never change once published."""
    if len(signature) != 64:
        raise RuntimeError("An install record's signature is 64 bytes")
    for key, body, kind in zip(keys(platform, tag), (data, signature), ("text/plain", "application/octet-stream")):
        created = r2.request("PUT", key, body=body, headers={"If-None-Match": "*", "Content-Type": kind})
        if created.status not in (200, 201, 412):
            raise RuntimeError(f"Install record upload failed for {platform} (HTTP {created.status})")
        if fetch(origin + key) != body:
            if created.status == 412:
                raise RuntimeError(f"A different {platform} install record is already published for {tag}")
            raise RuntimeError(f"The published {platform} install record does not match")


def sha256(data):
    return hashlib.sha256(data).hexdigest()
