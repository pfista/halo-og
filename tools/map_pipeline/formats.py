"""Read-only cache inventory; recognizing a container does not certify playability.

Header layouts are documented by Invader's ``include/invader/hek/map.hpp``.
Resource layouts follow ``include/invader/resource/hek/resource_map.hpp``.
No tag data is executed, decompressed, converted or written by this module.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import struct
from typing import BinaryIO, Callable


HEADER_BYTES = 0x800
RESOURCE_HEADER_BYTES = 0x10
RESOURCE_ENTRY_BYTES = 0xC
HASH_CHUNK_BYTES = 1024 * 1024
FORMATS = {5: "xbox", 6: "pc-demo", 7: "pc", 609: "custom-edition", 13: "mcc"}
RESOURCE_TYPES = {1: "bitmaps", 2: "sounds", 3: "loc"}

# Invader CacheFileDemoHeader: the signatures and fields are not at the
# ordinary PC/Xbox header offsets. These are byte offsets, not host structs.
DEMO_OFFSETS = {"type": 0x2, "head": 0x2C0, "tag_bytes": 0x2C4,
                "build": 0x2C8, "version": 0x588, "name": 0x58C,
                "declared_bytes": 0x5E8, "tag_data_offset": 0x5EC,
                "foot": 0x5F0}
STANDARD_OFFSETS = {"head": 0, "version": 4, "declared_bytes": 8,
                    "tag_data_offset": 0x10, "tag_bytes": 0x14,
                    "name": 0x20, "build": 0x40, "type": 0x60,
                    "foot": 0x7FC}


class FormatError(ValueError):
    """An inventory failure suitable for structured UI/CLI diagnostics."""

    def __init__(self, code: str, message: str, *, field: str | None = None,
                 value: object = None, suggested_fix: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.value = value
        self.suggested_fix = suggested_fix

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "field": self.field,
                "value": self.value, "suggested_fix": self.suggested_fix}


def _error(code: str, message: str, field: str | None = None,
           value: object = None, suggested_fix: str | None = None) -> FormatError:
    return FormatError(code, message, field=field, value=value,
                       suggested_fix=suggested_fix or
                       "Use an intact copy of the source map; do not edit its header.")


def _regular_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise _error("source_unavailable", f"Cannot inspect source file: {exc}",
                     "path", str(path), "Check that the source file exists and is readable.") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise _error("symlink_source", "Map inventory does not follow symlink files.",
                     "path", str(path), "Supply the actual map file or a regular copy.")
    if not stat.S_ISREG(metadata.st_mode):
        raise _error("not_regular_file", "Map source is not a regular file.",
                     "path", str(path), "Supply a regular .map file.")
    return metadata


def _read(stream: BinaryIO, offset: int, size: int, file_bytes: int, field: str) -> bytes:
    if offset < 0 or size < 0 or offset > file_bytes or size > file_bytes - offset:
        raise _error("out_of_bounds", "A header range lies outside the file.",
                     field, {"offset": offset, "bytes": size, "file_bytes": file_bytes})
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise _error("source_changed", "Source file became shorter during inventory.", field)
    return data


def _string(header: bytes, offset: int, field: str) -> str:
    data = header[offset:offset + 32]
    terminator = data.find(b"\0")
    if terminator < 0:
        raise _error("unterminated_string", "Cache header string has no terminator.", field)
    try:
        return data[:terminator].decode("ascii")
    except UnicodeDecodeError as exc:
        raise _error("invalid_string", "Cache header string is not ASCII.", field) from exc


def _inspect_header(header: bytes, file_bytes: int) -> dict:
    if len(header) < HEADER_BYTES:
        raise _error("truncated_header", "Cache file is shorter than its 2048-byte header.",
                     "file_bytes", file_bytes)
    if header[:4] == b"daeh":
        offsets, layout, foot = STANDARD_OFFSETS, "standard", b"toof"
    elif header[DEMO_OFFSETS["head"]:DEMO_OFFSETS["head"] + 4] == b"dehE":
        offsets, layout, foot = DEMO_OFFSETS, "pc-demo", b"tofG"
    else:
        raise _error("bad_signature", "Source is not a recognized Halo cache or resource map.",
                     "header_signature")
    if header[offsets["foot"]:offsets["foot"] + 4] != foot:
        raise _error("bad_signature", "Cache footer signature does not match its header layout.",
                     "footer_signature")
    version = struct.unpack_from("<I", header, offsets["version"])[0]
    if version not in FORMATS:
        raise _error("unsupported_version", "Cache version is not supported by this inventory.",
                     "version", version,
                     "Supply an Xbox v5, PC demo v6, PC v7, Custom Edition v609 or MCC CEA v13 cache.")
    if (layout == "pc-demo") != (version == 6):
        raise _error("wrong_header_layout", "Cache version and header layout disagree.",
                     "version", version)
    info = {"version": version, "format": FORMATS[version], "header_layout": layout,
            "name": _string(header, offsets["name"], "name"),
            "build": _string(header, offsets["build"], "build"),
            "type": struct.unpack_from("<H", header, offsets["type"])[0]}
    for field in ("declared_bytes", "tag_bytes", "tag_data_offset"):
        info[field] = struct.unpack_from("<I", header, offsets[field])[0]
    if info["type"] not in (0, 1, 2):
        raise _error("invalid_scenario_type", "Cache scenario type is not solo, multiplayer or UI.",
                     "type", info["type"])
    declared = info["declared_bytes"]
    if declared and declared < HEADER_BYTES:
        raise _error("invalid_declared_size", "Declared cache size cannot contain its header.",
                     "declared_bytes", declared)
    if version == 5 and not declared:
        raise _error("invalid_declared_size", "Xbox caches must declare their decompressed size.",
                     "declared_bytes", declared)
    # Xbox offsets refer to the decompressed cache, not the compressed disk file.
    # PC/CE tools may leave declared size zero; those use the physical file size.
    limit = declared if version == 5 else (declared or file_bytes)
    if version != 5 and limit > file_bytes:
        raise _error("invalid_declared_size", "Declared cache size exceeds the source file.",
                     "declared_bytes", declared)
    minimum_index_bytes = 0x24 if version == 5 else 0x28
    offset, size = info["tag_data_offset"], info["tag_bytes"]
    if offset < HEADER_BYTES or size < minimum_index_bytes or offset > limit or size > limit - offset:
        raise _error("invalid_tag_range", "Tag data does not fit the cache's addressable file range.",
                     "tag_data_range", {"offset": offset, "bytes": size, "limit": limit})
    return info


def _inspect_resources(stream: BinaryIO, header: bytes, file_bytes: int, path: Path) -> dict:
    kind, names_offset, index_offset, count = struct.unpack_from("<4I", header)
    if (names_offset < RESOURCE_HEADER_BYTES or index_offset < names_offset or
            index_offset > file_bytes or count > (file_bytes - index_offset) // RESOURCE_ENTRY_BYTES):
        raise _error("invalid_resource_header", "Resource map name/index tables do not fit the file.",
                     "resource_header", {"names_offset": names_offset,
                                          "index_offset": index_offset, "entries": count})
    # Read one entry/name at a time. File-provided counts never size an allocation.
    names_bytes = index_offset - names_offset
    for index in range(count):
        entry = _read(stream, index_offset + index * RESOURCE_ENTRY_BYTES,
                      RESOURCE_ENTRY_BYTES, file_bytes, f"resources[{index}]")
        name_offset, size, offset = struct.unpack("<3I", entry)
        if name_offset >= names_bytes:
            raise _error("invalid_resource_name", "Resource name lies outside its name table.",
                         f"resources[{index}].name_offset", name_offset)
        name = _read(stream, names_offset + name_offset, min(256, names_bytes - name_offset),
                     file_bytes, f"resources[{index}].name")
        if b"\0" not in name:
            raise _error("unterminated_resource_name", "Resource name has no bounded terminator.",
                         f"resources[{index}].name")
        if offset < RESOURCE_HEADER_BYTES or offset > file_bytes or size > file_bytes - offset:
            raise _error("invalid_resource_range", "Resource data lies outside its source file.",
                         f"resources[{index}].data", {"offset": offset, "bytes": size})
    return {"name": path.stem, "version": None, "format": "resource", "build": None,
            "type": kind, "declared_bytes": file_bytes, "tag_bytes": None,
            "tag_data_offset": None, "header_layout": "resource",
            "resource_type": RESOURCE_TYPES[kind], "resource_entries": count}


def inspect_cache(path: str | os.PathLike[str]) -> dict:
    """Inventory a regular cache/resource file without loading tags or changing it.

    Recognized malformed files raise ``FormatError``. Resource maps return
    ``format='resource'`` and ``resource_type``/``resource_entries``; cache-only
    fields (version, build, tag bytes/offset) are None. ``declared_bytes`` retains
    the cache's header value, including zero, rather than inventing a declaration.
    """
    source = Path(path)
    before = _regular_file(source)
    descriptor = None
    try:
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise _error("source_changed", "Source file changed while inventory opened it.", "path", str(source))
            file_bytes = opened.st_size
            header = stream.read(HEADER_BYTES)
            if len(header) < RESOURCE_HEADER_BYTES:
                raise _error("truncated_header", "Source cannot contain a cache or resource header.",
                             "file_bytes", file_bytes)
            first = struct.unpack_from("<I", header)[0]
            info = (_inspect_resources(stream, header, file_bytes, source)
                    if first in RESOURCE_TYPES else _inspect_header(header, file_bytes))
            stream.seek(0)
            digest = hashlib.sha256()
            hashed_bytes = 0
            while chunk := stream.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
                hashed_bytes += len(chunk)
            after = os.fstat(stream.fileno())
            current = _regular_file(source)
            if (hashed_bytes != file_bytes or opened.st_size != after.st_size or
                    opened.st_mtime_ns != after.st_mtime_ns or opened.st_ctime_ns != after.st_ctime_ns or
                    (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino)):
                raise _error("source_changed", "Source file changed during inventory.", "path", str(source))
            info.update(file_bytes=file_bytes, sha256=digest.hexdigest())
            return info
    except OSError as exc:
        raise _error("source_unavailable", f"Cannot read source file: {exc}", "path", str(source),
                     "Check that the source file is readable and supply a regular copy.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def discover_maps(directory: str | os.PathLike[str], recursive: bool = False, *,
                  on_error: Callable[[Path, FormatError], None] | None = None) -> list[Path]:
    """Return deterministic .map entries, including malformed files for inspection.

    Resources are included so callers can classify them with ``inspect_cache``.
    Symlink mapfiles/directories are rejected; recursive scanning never follows
    symlinks. Other non-map files are ignored. A directory named *.map remains an
    entry so inspection reports that it is not a regular file. The default is
    strict: any discovery failure raises ``FormatError``. An ``on_error`` callback
    receives rejected entries or unreadable folders and discovery continues with
    safe siblings. An invalid root is always rejected before scanning.
    """
    root = Path(directory)
    try:
        if root.is_symlink() or not root.is_dir():
            raise _error("invalid_directory", "Map source directory must be a real directory.",
                         "directory", str(root), "Supply a readable directory, not a symlink.")
    except OSError as exc:
        raise _error("directory_unavailable", f"Cannot scan map directory: {exc}",
                     "directory", str(root), "Check that the directory and its entries are readable.") from exc

    found = []

    def reject(entry: Path, error: FormatError) -> None:
        if on_error is None:
            raise error
        on_error(entry, error)

    def scan_error(entry: Path, exc: OSError) -> None:
        reject(entry, _error("directory_unavailable", f"Cannot scan map directory entry: {exc}",
                             "path", str(entry),
                             "Check that the directory and its entries are readable."))

    def visit(folder: Path) -> None:
        try:
            entries = sorted(folder.iterdir(), key=lambda p: (p.name.casefold(), p.name))
        except OSError as exc:
            scan_error(folder, exc)
            return
        for entry in entries:
            is_map = entry.suffix.casefold() == ".map"
            try:
                metadata = entry.lstat()
            except OSError as exc:
                scan_error(entry, exc)
                continue
            if stat.S_ISLNK(metadata.st_mode):
                if is_map or (recursive and entry.is_dir()):
                    reject(entry, _error("symlink_source", "Map discovery does not follow symlink entries.",
                                         "path", str(entry),
                                         "Supply actual directories and regular map files."))
                continue
            if is_map:
                found.append(entry)
            if recursive and stat.S_ISDIR(metadata.st_mode):
                visit(entry)

    visit(root)
    return sorted(found, key=lambda p: (p.relative_to(root).as_posix().casefold(),
                                        p.relative_to(root).as_posix()))
