#!/usr/bin/env python3
"""Explicitly download the optional timer pack into one user-selected directory."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__:
    from .map_catalog import publish_directory
    from .publish_map_catalog import HTTPS, PublishError
    from .timer_audio_pack import MANIFEST_KEY, MAX_MANIFEST_BYTES, validate_manifest, validate_wav
else:
    from map_catalog import publish_directory
    from publish_map_catalog import HTTPS, PublishError
    from timer_audio_pack import MANIFEST_KEY, MAX_MANIFEST_BYTES, validate_manifest, validate_wav

ORIGIN = "https://dl.oghalo.com/"
MANIFEST_URL = ORIGIN + MANIFEST_KEY


def checked_destination(destination):
    destination = Path(os.path.abspath(destination))
    if os.path.lexists(destination):
        raise PublishError("Timer destination already exists; existing recordings were preserved")
    if any(parent.is_symlink() for parent in destination.parents):
        raise PublishError("Timer destination must not have symlink parents")
    return destination


def fetch(http, url, limit):
    response = http.request("GET", url, headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"}, limit=limit)
    if response.status != 200:
        raise PublishError(f"Timer download failed (HTTP {response.status}); no pack was installed")
    if len(response.body) > limit:
        raise PublishError("Timer download exceeded its byte limit; no pack was installed")
    return response.body


def save_file(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def download_pack(destination, http=None):
    """Install all 46 reviewed WAVs together; preserve every existing directory."""
    destination = checked_destination(destination)
    http = http or HTTPS()
    manifest_bytes = fetch(http, MANIFEST_URL, MAX_MANIFEST_BYTES)
    manifest = validate_manifest(manifest_bytes)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Recheck after parent creation and before staging, including an existing
    # destination that appeared while the manifest request was in progress.
    destination = checked_destination(destination)
    staged = Path(tempfile.mkdtemp(prefix="." + destination.name + "-", suffix=".partial", dir=destination.parent))
    try:
        for entry in manifest["files"]:
            wav = fetch(http, ORIGIN + entry["object_key"], entry["file_bytes"])
            validate_wav(wav)
            if len(wav) != entry["file_bytes"] or hashlib.sha256(wav).hexdigest() != entry["sha256"]:
                raise PublishError("Timer recording failed its exact size or SHA-256 check; no pack was installed")
            save_file(staged / (entry["cue"] + ".wav"), wav)
        save_file(staged / "download-manifest.json", manifest_bytes)
        checked_destination(destination)
        publish_directory(staged, destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True, help="Exact sounds/performance directory beneath your game data or save root")
    args = parser.parse_args()
    try:
        destination = download_pack(args.destination)
    except (PublishError, OSError, ValueError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, PublishError) else "Timer pack could not be installed; existing files were preserved"
        parser.exit(1, "Timer download failed: " + message + "\n")
    print(f"Installed 46 optional timer recordings in {destination}. Restart Halo to enable Timer Audio.")


if __name__ == "__main__":
    main()
