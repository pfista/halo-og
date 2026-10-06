#!/usr/bin/env python3
"""Prepare reviewed optional timer WAVs locally; never convert tags or upload."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

if __package__:
    from .import_performance_audio import CUES
    from .map_catalog import publish_directory
    from .publish_map_catalog import PublishError, parse_json, read_regular
else:
    from import_performance_audio import CUES
    from map_catalog import publish_directory
    from publish_map_catalog import PublishError, parse_json, read_regular

ROOT = Path(__file__).resolve().parents[1]
PACK_ID = "performance-timer-v1"
MANIFEST_KEY = "audio/timer/v1/current.json"
MAX_WAV_BYTES = 1024 * 1024
MAX_PACK_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
ENTRY_FIELDS = {"cue", "file_bytes", "sha256", "object_key"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Prepared:
    directory: Path
    manifest: bytes
    files: tuple


def real_directory(path):
    """Reject selected or parent symlinks before inspecting an object tree."""
    path = Path(os.path.abspath(path))
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_dir():
        raise PublishError("Select a real directory without symlink parents")
    return path


def validate_wav(data):
    """Require exactly the canonical 44-byte little-endian PCM WAV layout."""
    if not isinstance(data, bytes) or not 44 < len(data) <= MAX_WAV_BYTES:
        raise PublishError("Timer WAV exceeds its byte bounds or has no samples")
    if (data[:4] != b"RIFF" or data[8:16] != b"WAVEfmt " or data[36:40] != b"data"
            or struct.unpack_from("<I", data, 4)[0] != len(data) - 8
            or struct.unpack_from("<I", data, 16)[0] != 16):
        raise PublishError("Timer WAV must have a canonical 44-byte PCM header")
    encoding, channels, rate, byte_rate, alignment, bits, samples = struct.unpack_from("<HHIIHH4xI", data, 20)
    if (encoding != 1 or channels not in (1, 2) or rate not in (22050, 44100)
            or bits != 16 or alignment != channels * 2 or byte_rate != rate * alignment
            or samples != len(data) - 44 or samples % alignment or samples > 4 * byte_rate):
        raise PublishError("Timer WAV must be 16-bit mono/stereo 22/44 kHz PCM of at most four seconds")
    return {"channels": channels, "sample_rate": rate, "frames": samples // alignment}


def validate_manifest(data):
    if len(data) > MAX_MANIFEST_BYTES:
        raise PublishError("Timer manifest exceeds its byte limit")
    manifest = parse_json(data)
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "pack_id", "files"}
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["pack_id"] != PACK_ID or not isinstance(manifest["files"], list)
            or len(manifest["files"]) != len(CUES)):
        raise PublishError("Timer manifest has an unsupported schema, pack or cue count")
    seen, total = set(), 0
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
            raise PublishError("Timer cue has unexpected fields")
        cue, digest, size = entry["cue"], entry["sha256"], entry["file_bytes"]
        if (not isinstance(cue, str) or cue not in CUES or cue in seen
                or not isinstance(digest, str) or not SHA256.fullmatch(digest)
                or type(size) is not int or not 44 < size <= MAX_WAV_BYTES
                or entry["object_key"] != f"audio/timer/sha256/{digest}/{cue}.wav"):
            raise PublishError("Timer cue identity, size, hash or immutable key is invalid")
        seen.add(cue)
        total += size
    if seen != set(CUES) or total > MAX_PACK_BYTES:
        raise PublishError("Timer manifest requires exactly 46 canonical cues within 32 MiB")
    return manifest


def validate_prepared(directory):
    directory = real_directory(directory)
    data = read_regular(directory / "manifest.json", MAX_MANIFEST_BYTES)
    manifest = validate_manifest(data)
    expected_files, expected_dirs = {"manifest.json"}, set()
    for entry in manifest["files"]:
        key = entry["object_key"]
        expected_files.add(key)
        parent = Path(key).parent
        while str(parent) != ".":
            expected_dirs.add(parent.as_posix())
            parent = parent.parent
    files, directories = set(), set()
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise PublishError("Timer pack must not contain symlinks")
        name = path.relative_to(directory).as_posix()
        if path.is_dir():
            directories.add(name)
        elif path.is_file():
            files.add(name)
        else:
            raise PublishError("Timer pack must contain only regular files")
    if files != expected_files or directories != expected_dirs:
        raise PublishError("Timer pack must contain exactly manifest.json and declared WAV objects")
    for entry in manifest["files"]:
        wav = read_regular(directory / entry["object_key"], MAX_WAV_BYTES)
        validate_wav(wav)
        if len(wav) != entry["file_bytes"] or hashlib.sha256(wav).hexdigest() != entry["sha256"]:
            raise PublishError("Timer WAV does not match its manifest size or SHA-256")
    return Prepared(directory, data, tuple(manifest["files"]))


def prepare_pack(source, output):
    source = real_directory(source)
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise PublishError("Prepared destination already exists; preserve it and select a new directory")
    if any(parent.is_symlink() for parent in output.parents):
        raise PublishError("Prepared destination must not have symlink parents")
    names = {cue + ".wav" for cue in CUES}
    inventory = list(source.iterdir())
    if ({path.name for path in inventory} - {"import-manifest.json"}) != names:
        raise PublishError("Source must contain exactly the 46 timer WAVs and optional local import-manifest.json")
    for path in inventory:
        if path.is_symlink() or not path.is_file():
            raise PublishError("Timer source must contain regular files without symlinks")
    # Snapshot validated bytes before staging. The importer provenance stays local.
    objects, entries = {}, []
    total = 0
    for cue in CUES:
        wav = read_regular(source / (cue + ".wav"), MAX_WAV_BYTES)
        validate_wav(wav)
        digest = hashlib.sha256(wav).hexdigest()
        key = f"audio/timer/sha256/{digest}/{cue}.wav"
        objects[key] = wav
        entries.append({"cue": cue, "file_bytes": len(wav), "sha256": digest, "object_key": key})
        total += len(wav)
    if total > MAX_PACK_BYTES:
        raise PublishError("Timer pack exceeds 32 MiB")
    manifest = (json.dumps({"schema_version": 1, "pack_id": PACK_ID, "files": entries}, indent=2) + "\n").encode()
    validate_manifest(manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix="." + output.name + "-", suffix=".partial", dir=output.parent))
    try:
        for key, wav in objects.items():
            path = staged / key
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(wav)
        with (staged / "manifest.json").open("xb") as stream:
            stream.write(manifest)
        validate_prepared(staged)
        publish_directory(staged, output)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return validate_prepared(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "assets/sounds/performance")
    parser.add_argument("--output", type=Path, default=ROOT / "build/timer-audio/prepared")
    args = parser.parse_args()
    try:
        prepared = prepare_pack(args.source, args.output)
    except (PublishError, OSError, ValueError):
        error = sys.exc_info()[1]
        message = str(error) if isinstance(error, PublishError) else "Local timer input could not be read or staged"
        parser.exit(1, "Timer preparation failed: " + message + "\n")
    print(f"Prepared {len(prepared.files)} timer cues ({sum(entry['file_bytes'] for entry in prepared.files)} bytes); no upload performed.")


if __name__ == "__main__":
    main()
