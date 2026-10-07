#!/usr/bin/env python3
"""Build opt-in map asset helpers using an existing, reviewed local toolchain.

This does not download, rebuild, patch, or install Invader or any dependency.
The receipt records the reused inputs; it does not claim fresh reproducibility
of libraries which were built before this invocation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


HERE = Path(__file__).resolve().parent
PINS = HERE / "community-toolchain/pins.json"
HELPERS = HERE / "map_conversion"
SOURCES = {"audio": "convert_audio.cpp", "bitmaps": "convert_bitmaps.cpp",
           "mips": "select_native_mips.cpp", "packing": "pack_lossless_bitmaps.cpp",
           "extensions": "omit_mcc_extensions.cpp", "hud": "normalize_mcc_hud.cpp"}
STATIC_DEPENDENCIES = ("FLAC", "vorbisenc", "vorbisfile", "vorbis", "ogg", "samplerate", "squish")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required: " + str(path))
    return value


def tree_fingerprint(root, headers_only=False):
    """Hash sorted names and contents, excluding Git's mutable administrative data."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError("Missing include/source directory: " + str(root))
    records = []
    for directory, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Directory symlink cannot be fingerprinted: " + str(Path(directory) / name))
        for name in sorted(files):
            path = Path(directory) / name
            if name == ".git" or (headers_only and path.suffix.lower() not in (".h", ".hpp", ".hxx", ".inc")):
                continue
            # Header symlinks may be part of a local prefix. Capture both their
            # spelling and the bytes the compiler actually reads.
            record = {"file": path.relative_to(root).as_posix(), "sha256": sha256(path)}
            if path.is_symlink():
                target = path.resolve(strict=True)
                if not target.is_relative_to(root.resolve()):
                    raise ValueError("External source/header symlink: " + str(path))
                record["symlink"] = os.readlink(path)
            records.append(record)
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"sha256": hashlib.sha256(encoded).hexdigest(), "files": len(records)}


def source_provenance(source, commit, manifest):
    record = {"declared_commit": commit, "tree": tree_fingerprint(source),
              "local_changes_declared": manifest.get("local_changes", []),
              "source_patches_declared": manifest.get("source_patches", [])}
    if (source / ".git").exists():
        command = ["git", "-C", str(source)]
        head = subprocess.check_output(command + ["rev-parse", "HEAD"], text=True).strip()
        if head != commit:
            raise ValueError("Invader checkout HEAD differs from the reviewed commit")
        record["git_head"] = head
        record["git_status"] = subprocess.check_output(command + ["status", "--porcelain=v1"], text=True)
        record["git_diff_sha256"] = hashlib.sha256(subprocess.check_output(command + ["diff", "HEAD", "--binary"])).hexdigest()
    else:
        # Extracted source has no Git administrative state. Its manifest and
        # content fingerprint remain explicit; no clean-checkout claim is made.
        record["git_head"] = None
    return record


def validated_layout(toolchain, manifest_path, selected):
    root = Path(toolchain).resolve(strict=True)
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = read_json(manifest_path)
    pins = read_json(PINS)
    for field in ("invader_commit", "riat_commit"):
        if manifest.get(field) != pins[field]:
            raise ValueError("Source manifest differs from the reviewed " + field)
    if manifest.get("invader_repository", pins["invader_repository"]) != pins["invader_repository"]:
        raise ValueError("Source manifest names a different Invader repository")
    sources = [path for path in (root / "invader", root / "sources/invader") if path.is_dir()]
    if len(sources) != 1:
        raise ValueError("Toolchain needs exactly one Invader source layout: invader or sources/invader")
    source = sources[0]
    includes = {"invader": source / "include", "generated": root / "build", "prefix": root / "prefix/include"}
    for path in includes.values():
        if not path.is_dir():
            raise ValueError("Missing include directory: " + str(path))
    candidates = sorted(path for path in (root / "riat-build").rglob("libriatc.a")
                        if path.is_file() and path.parent.name == "release")
    if len(candidates) != 1:
        raise ValueError("Toolchain needs one unique release libriatc.a under riat-build")
    libraries = {"invader": root / "build/libinvader.a", "riat": candidates[0]}
    libraries.update({name: root / "prefix/lib" / ("lib" + name + ".a") for name in STATIC_DEPENDENCIES})
    zlib = root / "prefix/lib/libz.a"
    if zlib.is_file():
        libraries["z"] = zlib
    elif sys.platform != "darwin":
        raise ValueError("Toolchain prefix needs static libz.a on this host")
    for path in libraries.values():
        if not path.is_file():
            raise ValueError("Missing reviewed static library: " + str(path))
    helpers = {name: (HELPERS / SOURCES[name]).resolve(strict=True) for name in selected}
    return root, manifest_path, manifest, pins, source, includes, libraries, helpers


def input_snapshot(manifest_path, source, includes, libraries, helpers, pins, manifest):
    return {"source_manifest": {"file": str(manifest_path), "sha256": sha256(manifest_path)},
            "recipe_pins": {"file": str(PINS), "sha256": sha256(PINS)},
            "invader_source": {"directory": str(source), **source_provenance(source, pins["invader_commit"], manifest)},
            "includes": {name: {"directory": str(path), **tree_fingerprint(path, headers_only=name == "generated")}
                         for name, path in includes.items()},
            "libraries": {name: {"file": str(path), "sha256": sha256(path)} for name, path in libraries.items()},
            "helper_sources": {name: {"file": str(path), "sha256": sha256(path)} for name, path in helpers.items()}}


def compile_command(compiler, source, output, includes, libraries):
    command = [compiler, "-std=c++20", "-O2"]
    command += ["-I" + str(path) for path in includes.values()]
    command += [str(source), str(libraries["invader"])]
    command += [str(libraries["z"])] if "z" in libraries else ["-lz"]
    command += [str(libraries[name]) for name in STATIC_DEPENDENCIES]
    command += [str(libraries["riat"])]
    if sys.platform == "darwin":
        command += ["-framework", "Security", "-framework", "CoreFoundation", "-liconv"]
    elif sys.platform.startswith("linux"):
        command += ["-ldl", "-lpthread", "-lm"]
    else:
        raise ValueError("Asset helper recipe currently supports native macOS and Linux hosts")
    return command + ["-o", str(output)]


def build(toolchain, invader_manifest, output, compiler="c++", tools="all"):
    if tools not in (*SOURCES, "all"):
        raise ValueError("Unknown asset helper selection")
    selected = tuple(SOURCES) if tools == "all" else (tools,)
    output = Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output must be a new directory: " + str(output))
    layout = validated_layout(toolchain, invader_manifest, selected)
    root, manifest_path, manifest, pins, source, includes, libraries, helpers = layout
    resolved_output = output.resolve()
    if resolved_output.is_relative_to(root) or resolved_output.is_relative_to(HELPERS.resolve()):
        raise ValueError("Output must be outside the preserved toolchain and helper source trees")
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise ValueError("C++ compiler not found: " + compiler)
    compiler_path = str(Path(compiler_path).resolve())
    version = subprocess.check_output([compiler_path, "--version"], text=True, stderr=subprocess.STDOUT).strip()
    before = input_snapshot(manifest_path, source, includes, libraries, helpers, pins, manifest)
    # All input checks precede creating output. Compiler logs stay with a failed
    # build, and the success manifest is written only after unchanged-input checks.
    output.mkdir(parents=True)
    commands = {}
    binaries = {}
    for name, helper_source in helpers.items():
        binary = output / ("convert-" + name)
        command = compile_command(compiler_path, helper_source, binary, includes, libraries)
        commands[name] = command
        (output / (name + "-compile-command.json")).write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
        with (output / (name + "-compile.log")).open("wb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(name + " helper compilation failed; see " + str(output / (name + "-compile.log")))
        if not binary.is_file() or binary.stat().st_size == 0:
            raise RuntimeError("Compiler did not produce a nonempty " + name + " helper")
        binaries[name] = {"file": binary.name, "sha256": sha256(binary), "source_sha256": before["helper_sources"][name]["sha256"]}
    after = input_snapshot(manifest_path, source, includes, libraries, helpers, pins, manifest)
    if before != after:
        raise RuntimeError("Preserved toolchain/helper inputs changed during compilation; no trusted asset-tools manifest written")
    receipt = {"schema": 1, "invader_commit": pins["invader_commit"], "riat_commit": pins["riat_commit"],
               "binaries": binaries, "libraries": before["libraries"],
               "source_manifest_sha256": before["source_manifest"]["sha256"],
               "compiler": {"file": compiler_path, "version": version, "sha256": sha256(compiler_path)},
               "build_commands": commands, "inputs": before, "inputs_unchanged": True,
               "reused_libraries": True, "system_linker_libraries": ["z"] if "z" not in libraries else []}
    (output / "asset-tools.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True, help="Existing local Invader source/build/prefix root")
    parser.add_argument("--invader-manifest", type=Path, required=True, help="Reviewed source manifest with pinned Invader and RIAT commits")
    parser.add_argument("--output", type=Path, required=True, help="New asset helper output directory")
    parser.add_argument("--compiler", default="c++", help="Native C++ compiler executable (default: c++)")
    parser.add_argument("--tools", choices=(*SOURCES, "all"), default="all")
    args = parser.parse_args(argv)
    try:
        receipt = build(args.toolchain, args.invader_manifest, args.output, args.compiler, args.tools)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, "Asset helper build failed: " + str(error) + "\n")
    print("Built " + ", ".join(receipt["binaries"]) + "; receipt: " + str(args.output / "asset-tools.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
