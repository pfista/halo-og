"""Bounded lossless .mapog transport for audited whole-asset packages.

48-byte <8sQ32s header: HOGMAP2\\n, expanded byte count, binary SHA-256;
then exactly one RFC1950 zlib stream. No filenames, executable paths or stock
assets are introduced by this envelope. The expanded HOGPKG1 manifest retains
all original-tag references, literal hashes and exact rebuilt-map checks.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import struct
import tempfile
import zlib

MAGIC = b"HOGMAP2\n"
RAW_MAGIC = b"HOGPKG1\n"
HEADER = struct.Struct("<8sQ32s")
MAX_BYTES = 256 * 1024 * 1024
CHUNK = 65536


def _regular(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Package must be a regular file without links or reparse points")
    if not 18 <= info.st_size <= MAX_BYTES:
        raise ValueError("Package exceeds its permitted byte limits")
    return path


def _digest(path):
    h = hashlib.sha256()
    with _open_regular(path) as file:
        for chunk in iter(lambda: file.read(CHUNK), b""): h.update(chunk)
    return h.digest()


@contextmanager
def _open_regular(path):
    path = _regular(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) |
                 getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0))
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or not 18 <= info.st_size <= MAX_BYTES or
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Package must be a bounded regular file without links")
        yield file


def is_compressed(path):
    with _open_regular(path) as file:
        return file.read(8) == MAGIC


def compress_package(source, destination):
    source, destination = _regular(source), Path(destination)
    size, expected = source.stat().st_size, _digest(source)
    with _open_regular(source) as file:
        if file.read(8) != RAW_MAGIC: raise ValueError("Compression requires a raw HOGPKG1 package")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        h, read_bytes, compressed_bytes = hashlib.sha256(), 0, HEADER.size
        with os.fdopen(fd, "wb") as output, _open_regular(source) as file:
            output.write(HEADER.pack(MAGIC, size, expected))
            compressor = zlib.compressobj(9)
            for chunk in iter(lambda: file.read(CHUNK), b""):
                read_bytes += len(chunk); h.update(chunk)
                data = compressor.compress(chunk)
                compressed_bytes += len(data)
                if read_bytes > size or compressed_bytes > MAX_BYTES: raise ValueError("Package changed or compressed output exceeds limits")
                output.write(data)
            tail = compressor.flush()
            compressed_bytes += len(tail)
            if compressed_bytes > MAX_BYTES or read_bytes != size or h.digest() != expected:
                raise ValueError("Raw package changed during compression")
            output.write(tail); output.flush(); os.fsync(output.fileno())
        return {"compressed_bytes": compressed_bytes, "expanded_bytes": size,
                "expanded_sha256": expected.hex(), "sha256": _digest(destination).hex()}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def expand_package(source, destination):
    source, destination = _regular(source), Path(destination)
    with _open_regular(source) as file:
        compressed_size = os.fstat(file.fileno()).st_size
        raw_header = file.read(HEADER.size)
        if len(raw_header) != HEADER.size: raise ValueError("Truncated .mapog header")
        magic, expected_bytes, expected_hash = HEADER.unpack(raw_header)
        if magic != MAGIC or not 18 <= expected_bytes <= MAX_BYTES:
            raise ValueError("Invalid .mapog magic or expansion bound")
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            h, written, prefix, consumed = hashlib.sha256(), 0, bytearray(), HEADER.size
            decoder = zlib.decompressobj()
            with os.fdopen(fd, "wb") as output:
                for chunk in iter(lambda: file.read(CHUNK), b""):
                    consumed += len(chunk)
                    if consumed > compressed_size or consumed > MAX_BYTES:
                        raise ValueError("Compressed package changed or exceeds its byte limit")
                    if decoder.eof: raise ValueError("Trailing compressed data is forbidden")
                    while chunk:
                        expanded = decoder.decompress(chunk, min(CHUNK, expected_bytes - written + 1))
                        if len(expanded) > expected_bytes - written: raise ValueError(".mapog expansion exceeds its exact bound")
                        written += len(expanded); h.update(expanded)
                        if len(prefix) < 8: prefix.extend(expanded[:8 - len(prefix)])
                        output.write(expanded)
                        chunk = decoder.unconsumed_tail
                        if decoder.unused_data: raise ValueError("Trailing compressed data is forbidden")
                if (consumed != compressed_size or os.fstat(file.fileno()).st_size != compressed_size
                        or not decoder.eof or written != expected_bytes or h.digest() != expected_hash or prefix != RAW_MAGIC):
                    raise ValueError(".mapog stream, expanded size, SHA-256 or inner magic differs")
                output.flush(); os.fsync(output.fileno())
            return {"expanded_bytes": written, "expanded_sha256": expected_hash.hex()}
        except zlib.error:
            destination.unlink(missing_ok=True)
            raise ValueError("Invalid .mapog compression stream") from None
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


@contextmanager
def raw_package(path):
    """Expand only into an owned private temporary directory; always clean it."""
    path = _regular(path)
    with _open_regular(path) as file: magic = file.read(8)
    if magic == RAW_MAGIC:
        yield path
    elif magic == MAGIC:
        with tempfile.TemporaryDirectory(prefix="halo-mapog-") as temporary:
            expanded = Path(temporary) / "content.hogpkg"
            expand_package(path, expanded)
            yield expanded
    else:
        raise ValueError("Unknown community package format")
