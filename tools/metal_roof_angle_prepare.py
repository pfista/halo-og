#!/usr/bin/env python3
"""Prepare an isolated original ANGLE camera/draw diagnostic without running it.

The guest retains the frozen original object set. Only the existing capture
shim gains read-only raw render.camera/render.frustum records. This is not a
full current-source game rebuild or a native Metal parity result.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ROOT.parent / "pfista-halo-macos"
LLVM = Path("/opt/homebrew/opt/llvm@22/bin")
LINKER = Path("/opt/homebrew/opt/lld@22/bin/ld.lld")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Diagnostic source anchor must be unique: " + old[:80])
    return text.replace(old, new)


def camera_capture_source():
    addition = r'''
    /* Read-only diagnostic snapshot at this exact submitted original draw.
       Offsets/sizes are emitted by the actual ILP32 compiler, not guessed. */
    fprintf(file, ",\"render_camera_diagnostic\":{\"schema_version\":1,\"render_frame_index\":%ld,\"render_scene_index\":%ld,\"window_index\":%d,\"long_bytes\":%lu,\"float_bytes\":%lu,\"camera_size\":%lu,\"frustum_size\":%lu,\"camera_offsets\":{\"position\":%lu,\"forward\":%lu,\"up\":%lu,\"mirrored\":%lu,\"vertical_field_of_view\":%lu,\"viewport_bounds\":%lu,\"window_bounds\":%lu,\"z_near\":%lu,\"z_far\":%lu,\"mirror_plane\":%lu},\"frustum_offsets\":{\"bounds\":%lu,\"world_to_view\":%lu,\"view_to_world\":%lu,\"z_near\":%lu,\"z_far\":%lu,\"projection_valid\":%lu,\"projection_matrix\":%lu,\"projection_world_to_screen\":%lu},\"camera_blob\":",
        render.frame_index, render.scene_index, (int)render.window_index,
        (unsigned long)sizeof(long), (unsigned long)sizeof(real),
        (unsigned long)sizeof(render.camera), (unsigned long)sizeof(render.frustum),
        (unsigned long)offsetof(struct render_camera, position), (unsigned long)offsetof(struct render_camera, forward),
        (unsigned long)offsetof(struct render_camera, up), (unsigned long)offsetof(struct render_camera, mirrored),
        (unsigned long)offsetof(struct render_camera, vertical_field_of_view), (unsigned long)offsetof(struct render_camera, viewport_bounds),
        (unsigned long)offsetof(struct render_camera, window_bounds), (unsigned long)offsetof(struct render_camera, z_near),
        (unsigned long)offsetof(struct render_camera, z_far), (unsigned long)offsetof(struct render_camera, mirror_plane),
        (unsigned long)offsetof(struct render_frustum, frustum_bounds), (unsigned long)offsetof(struct render_frustum, world_to_view),
        (unsigned long)offsetof(struct render_frustum, view_to_world), (unsigned long)offsetof(struct render_frustum, z_near),
        (unsigned long)offsetof(struct render_frustum, z_far), (unsigned long)offsetof(struct render_frustum, projection_valid),
        (unsigned long)offsetof(struct render_frustum, projection_matrix), (unsigned long)offsetof(struct render_frustum, projection_world_to_screen));
    blob(file, &render.camera, sizeof(render.camera));
    fputs(",\"frustum_blob\":", file); blob(file, &render.frustum, sizeof(render.frustum));
    fputc('}', file);
'''
    return '#include "cseries.h"\n#include "render/render.h"\n#include <stddef.h>\n' + \
        'void metal_roof_camera_capture(FILE *file, void (*blob)(FILE *, const void *, unsigned long))\n{\n' + addition + '\n}\n'


def camera_capture_header(text):
    text = once(text, "extern unsigned char rasterizer_globals[];", """extern unsigned char rasterizer_globals[];
extern void metal_roof_camera_capture(FILE *, void (*)(FILE *, const void *, unsigned long));""")
    marker = '\tfputs(",\\\"fixed_attributes\\\":", file); metal_frame_blob(file, device.attributes, sizeof(device.attributes));'
    return once(text, marker, marker + '\n\tmetal_roof_camera_capture(file, metal_frame_blob);\n')


def float32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def camera_text(pose, vertical_fov):
    x, y, z, yaw, pitch = pose
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    # Existing original camera-load route accepts the observer's FOV; this is
    # deliberately only a requested pose. Raw rendered camera/frustum decide
    # the actual match, including roll and safe-frame projection adjustments.
    rows = ([x, y, z], [cy*cp, sy*cp, sp], [-cy*sp, -sy*sp, cp],
            [2*math.atan(math.tan(math.radians(vertical_fov)/2)*4/3)])
    return "\n".join(" ".join(format(float32(v), ".9g") for v in row) for row in rows) + "\n"


def dependency_paths(depfile):
    text = Path(depfile).read_text().replace("\\\n", " ")
    return [Path(name) if Path(name).is_absolute() else PRIMARY / name
            for name in shlex.split(text.split(":", 1)[1])]


def prepare(out, prior, current_object_baseline=False):
    out = out.resolve(); prior = prior.resolve()
    if out.exists():
        raise ValueError("Output already exists; preserve previous preparation")
    for tool in (LLVM / "clang", LLVM / "opt", LLVM / "llc", LINKER):
        if not tool.is_file():
            raise ValueError("Existing explicit toolchain executable missing: " + str(tool))
    historical = ROOT / "build/metal-reference-20261004/ordered-frame-runtime"
    original = ROOT / "build/macos-capture/provenance.json"
    provenance = json.loads(original.read_text())
    old_rsp = historical / "halo_guest.elf.rsp"
    inputs = shlex.split(old_rsp.read_text())
    expected = {x["path"]: x["sha256"] for x in provenance["input_objects"] + provenance["generated_artifacts"]}
    excluded = {str(historical / "d3d8_gl.o"), str(historical / "imports.o")}
    current_graph = None
    added = []
    if current_object_baseline:
        current_graph = subprocess.check_output(["/opt/homebrew/bin/ninja", "-t", "query", "build/macos/halo_guest.elf"], cwd=PRIMARY, text=True)
        graph_objects = {str(PRIMARY / line.strip()) for line in current_graph.splitlines() if line.strip().endswith(".o")}
        replacements = {str(PRIMARY / "build/macos/guest/obj/port/linux/src" / (name + ".o")) for name in ("d3d8_gl", "nv2a_vsh", "nv2a_psh")}
        replacements.add(str(PRIMARY / "build/macos/guest/obj/gen/imports.o"))
        added = sorted(graph_objects - set(inputs) - replacements)
        inputs.extend(added)
    object_hashes = {}
    drift = []
    for filename in inputs:
        if filename in excluded:
            continue
        if filename not in expected and filename not in added:
            raise ValueError("Frozen original object is missing/changed/unbound: " + filename)
        actual = sha(filename)
        if filename in added or actual != expected[filename]:
            if not current_object_baseline:
                raise ValueError("Frozen original object changed: " + filename)
            drift.append({"path": filename, "historical_sha256": expected.get(filename), "current_sha256": actual,
                          "added_current_graph_object": filename in added})
        object_hashes[filename] = actual
    bindings = {str(original): sha(original), str(old_rsp): sha(old_rsp), str(Path(__file__).resolve()): sha(__file__)}
    for name in ("d3d8_gl.c", "metal_frame_capture.h", "metal_frame_readback.h", "extra-imports.list", "build_guest.py"):
        path = historical / name
        bindings[str(path)] = sha(path)
    for path in (PRIMARY / "build/macos/halo", PRIMARY / "build/macos/guest/libguestc.a", PRIMARY / "build/macos/guest_rebase.dylib"):
        bindings[str(path)] = sha(path)
    for entry in ("host", "libguestc", "rebase_plugin"):
        if sha(provenance[entry]["path"]) != provenance[entry]["sha256"]:
            if entry != "host" or not current_object_baseline:
                raise ValueError("Frozen original " + entry + " changed")
    for path in (PRIMARY / "source/render/render.h", PRIMARY / "source/render/render_cameras.h", PRIMARY / "source/render/render.c",
                 PRIMARY / "source/render/render_cameras.c", ROOT / "build/metal-poc-0.6/roof-settled-comparison/capture_roof.py"):
        bindings[str(path)] = sha(path)
    libs = [PRIMARY / f"build/macos/angle/dist/{kind}.xcframework/macos-arm64/lib{kind}.framework/lib{kind}"
            for kind in ("EGL", "GLESv2")]
    if not all(path.is_file() for path in libs):
        raise ValueError("The two explicit original ANGLE library paths are required")
    bindings.update({str(path): sha(path) for path in libs})
    out.mkdir(parents=True)
    if current_graph is not None:
        (out / "current-ninja-graph.txt").write_text(current_graph)
    shutil.copy2(historical / "halo_guest.elf", out / "historical-original-guest.elf")
    bindings[str(historical / "halo_guest.elf")] = sha(historical / "halo_guest.elf")
    snapshot = out / "input-objects"; snapshot.mkdir()
    mapping = {}
    for index, filename in enumerate(inputs):
        if filename in excluded:
            mapping[filename] = str(out / Path(filename).name)
        else:
            dest = snapshot / (f"{index:04d}-" + Path(filename).name)
            shutil.copy2(filename, dest)
            if sha(dest) != object_hashes[filename]:
                raise ValueError("Object snapshot changed during copy")
            mapping[filename] = str(dest)
    for name in ("d3d8_gl.c", "metal_frame_readback.h", "extra-imports.list"):
        shutil.copy2(historical / name, out / name)
    (out / "metal_frame_capture.h").write_text(camera_capture_header((historical / "metal_frame_capture.h").read_text()))
    (out / "roof_camera_capture.c").write_text(camera_capture_source())
    shutil.copy2(__file__, out / "preparation-helper.py")
    (out / "halo_guest.elf.rsp").write_text("\n".join(shlex.quote(mapping[x]) for x in inputs) + "\n")
    command_output = subprocess.run(["/opt/homebrew/bin/ninja", "-t", "commands", "build/macos/guest/obj/port/linux/src/d3d8_gl.o"],
                                    cwd=PRIMARY, capture_output=True, text=True, check=True).stdout
    (out / "original-build-command.txt").write_text(command_output)
    line = next(x for x in command_output.splitlines() if x.startswith("tools/macos_guest_cc.py ") and " -S port/linux/src/d3d8_gl.c " in x)
    args = [x for x in shlex.split(line.split(" && ")[0])[1:] if x != "-MMD"]
    args[args.index("-MF")+1] = str(out / "d3d8_gl.d")
    args[args.index("-o")+1] = str(out / "d3d8_gl.ll")
    args = [str(out / "d3d8_gl.c") if x == "port/linux/src/d3d8_gl.c" else x for x in args]
    defines = ["-emit-llvm", "-DHALO_MACOS=1", "-DHALO_MACOS_METAL_SHADER_CAPTURE=1", "-DHALO_MACOS_METAL_FRAME_CAPTURE=1"]
    dependency_command = [str(LLVM / "clang"), *args, *defines, "-M", "-MF", str(out / "preflight.d")]
    steps = [(dependency_command, "dependencies")]
    observed = []
    def run(command, label):
        with (out / (label + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=PRIMARY, stdout=log, stderr=subprocess.STDOUT)
        observed.append({"label": label, "command": command, "exit_code": result.returncode})
        if result.returncode:
            write(out / "preparation-failure.json", {"commands": observed, "gpu_executed": False})
            raise ValueError("Original diagnostic build failed at " + label)
    host_path = PRIMARY / "build/macos/halo"
    fresh_host = None
    if current_object_baseline:
        # Reuse the original host builder without its setup, packaging, download
        # or primary output side effects. All objects/output remain in this test.
        module_path = PRIMARY / "tools/macos_build.py"
        bindings[str(module_path)] = sha(module_path)
        sys.path.insert(0, str(PRIMARY))
        spec = importlib.util.spec_from_file_location("original_angle_host_builder", module_path)
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        host_build = out / "fresh-angle-host"
        (host_build / "host").mkdir(parents=True)
        table = PRIMARY / "build/macos/host/host_import_table.c"
        bindings[str(table)] = sha(table); shutil.copy2(table, host_build / "host/host_import_table.c")
        sparkle = PRIMARY / "build/macos/sparkle/Sparkle.framework"
        if not sparkle.is_dir():
            raise ValueError("Existing original Sparkle dependency required; no download permitted")
        companion = PRIMARY / "build/macos/angle/dist/EGL.xcframework/macos-arm64/libEGL.framework/libGLESv2.dylib"
        target = PRIMARY / "build/macos/angle/dist/GLESv2.xcframework/macos-arm64/libGLESv2.framework/libGLESv2"
        if not companion.is_symlink() or companion.resolve() != target.resolve():
            raise ValueError("Existing original ANGLE companion must already be correct; no dependency edits")
        builder.BUILD = host_build
        builder.SDL = Path("/opt/homebrew/opt/sdl3")
        builder.GL = PRIMARY / "build/macos/toolchain/gl"
        builder.ANGLE = PRIMARY / "build/macos/angle/dist"
        builder.setup_sparkle = lambda: sparkle
        host_commands = []
        def host_run(*items):
            command = [str(item) for item in items]
            label = "host-" + str(len(host_commands))
            if "-c" in command:
                source = Path(command[command.index("-c")+1])
                bindings[str(source)] = sha(source)
                if source.suffix != ".s":
                    dep = out / (label + ".d")
                    run([*command, "-M", "-MF", str(dep)], label + "-dependencies")
                    for path in dependency_paths(dep):
                        if not path.is_relative_to(out):
                            bindings[str(path)] = sha(path)
            run(command, label)
            host_commands.append(command)
        builder.run = host_run
        builder.build_host()
        host_path = host_build / "halo"
        fresh_host = {"file": str(host_path), "sha256": sha(host_path), "builder": str(module_path),
                      "commands": host_commands, "primary_outputs_modified": False, "dependencies_downloaded": False}
        for module in list(sys.modules.values()):
            filename = getattr(module, "__file__", None)
            if filename and Path(filename).is_relative_to(PRIMARY) and Path(filename).is_file():
                bindings[str(Path(filename))] = sha(filename)
    rebuilt = []
    for index, change in enumerate(drift):
        filename = Path(change["path"])
        relative = filename.relative_to(PRIMARY)
        command_text = subprocess.run(["/opt/homebrew/bin/ninja", "-t", "commands", str(relative)],
                                      cwd=PRIMARY, capture_output=True, text=True, check=True).stdout
        label = "cache-coherence-" + str(index)
        (out / (label + "-command.txt")).write_text(command_text)
        first = next(line for line in command_text.splitlines() if line.startswith("tools/macos_guest_cc.py ") and " -S " in line)
        a = [x for x in shlex.split(first.split(" && ")[0])[1:] if x != "-MMD"]
        unit = out / "current-object-rebuild" / str(index)
        unit.mkdir(parents=True)
        a[a.index("-MF")+1] = str(unit / "preflight.d")
        a[a.index("-o")+1] = str(unit / "unit.ll")
        run([str(LLVM / "clang"), *a, "-emit-llvm", "-DHALO_MACOS=1", "-M"], label + "-dependencies")
        for path in dependency_paths(unit / "preflight.d"):
            bindings[str(path)] = sha(path)
            retained = out / "source-snapshot" / path.relative_to(PRIMARY)
            retained.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, retained)
        a[a.index("-MF")+1] = str(unit / "actual.d")
        run([str(LLVM / "clang"), *a, "-emit-llvm", "-DHALO_MACOS=1", "-MD"], label + "-compile")
        run([str(LLVM / "opt"), "-load-pass-plugin=" + str(PRIMARY / "build/macos/guest_rebase.dylib"),
             "-passes=halo-rebase,verify", "-S", str(unit / "unit.ll"), "-o", str(unit / "rebased.ll")], label + "-rebase")
        run([str(LLVM / "llc"), "-O2", "-mtriple=arm64_32-apple-watchos", "-aarch64-neon-syntax=generic", "-emulated-tls",
             str(unit / "rebased.ll"), "-o", str(unit / "darwin.s")], label + "-codegen")
        run(["/opt/homebrew/bin/python3", str(PRIMARY / "tools/android_asm_convert.py"), str(unit / "darwin.s"), str(unit / "unit.s")], label + "-convert")
        run([str(LLVM / "clang"), "--target=aarch64-linux-android", "-c", str(unit / "unit.s"), "-o", str(unit / "unit.o")], label + "-assemble")
        if sha(unit / "unit.o") != change["current_sha256"]:
            write(out / "cache-coherence-failure.json", {"object": change, "fresh_rebuild_sha256": sha(unit / "unit.o"),
                                                        "gpu_executed": False, "cached_object_not_substituted": True})
            raise ValueError("Current cached object does not match a fresh source/flag-bound rebuild: " + change["path"])
        if set(dependency_paths(unit / "preflight.d")) != set(dependency_paths(unit / "actual.d")):
            raise ValueError("Changed object compiler dependency set drifted")
        rebuilt.append({**change, "fresh_rebuild_sha256": sha(unit / "unit.o"), "fresh_rebuild_matches_current_cache": True})
        print("current cache object coherence", index+1, "/", len(drift), "passed", flush=True)
    for command, label in steps:
        run(command, label)
    # Keep engine structure declarations in their normal game compilation
    # environment, separate from the GL platform unit's libc declarations.
    camera_commands = subprocess.run(["/opt/homebrew/bin/ninja", "-t", "commands", "build/macos/guest/obj/source/render/render.o"],
                                     cwd=PRIMARY, capture_output=True, text=True, check=True).stdout
    (out / "camera-build-command.txt").write_text(camera_commands)
    line = next(line for line in camera_commands.splitlines() if line.startswith("tools/macos_guest_cc.py ") and " -S source/render/render.c " in line)
    camera_args = [x for x in shlex.split(line.split(" && ")[0])[1:] if x != "-MMD"]
    camera_args[camera_args.index("-MF")+1] = str(out / "camera-preflight.d")
    camera_args[camera_args.index("-o")+1] = str(out / "camera.ll")
    camera_args = [str(out / "roof_camera_capture.c") if x == "source/render/render.c" else x for x in camera_args]
    run([str(LLVM / "clang"), *camera_args, "-emit-llvm", "-DHALO_MACOS=1", "-M"], "camera-dependencies")
    for path in dependency_paths(out / "camera-preflight.d"):
        if not path.is_relative_to(out):
            bindings[str(path)] = sha(path)
    camera_args[camera_args.index("-MF")+1] = str(out / "camera-actual.d")
    camera_steps = [([str(LLVM / "clang"), *camera_args, "-emit-llvm", "-DHALO_MACOS=1", "-MD"], "camera-compile"),
        ([str(LLVM / "opt"), "-load-pass-plugin=" + str(PRIMARY / "build/macos/guest_rebase.dylib"), "-passes=halo-rebase,verify", "-S", str(out / "camera.ll"), "-o", str(out / "camera.rebased.ll")], "camera-rebase"),
        ([str(LLVM / "llc"), "-O2", "-mtriple=arm64_32-apple-watchos", "-aarch64-neon-syntax=generic", "-emulated-tls", str(out / "camera.rebased.ll"), "-o", str(out / "camera.darwin.s")], "camera-codegen"),
        (["/opt/homebrew/bin/python3", str(PRIMARY / "tools/android_asm_convert.py"), str(out / "camera.darwin.s"), str(out / "camera.s")], "camera-assembly-convert"),
        ([str(LLVM / "clang"), "--target=aarch64-linux-android", "-c", str(out / "camera.s"), "-o", str(out / "camera.o")], "camera-assemble")]
    for command, label in camera_steps:
        run(command, label)
    if set(dependency_paths(out / "camera-preflight.d")) != set(dependency_paths(out / "camera-actual.d")):
        raise ValueError("Camera helper dependency set changed")
    with (out / "halo_guest.elf.rsp").open("a") as response:
        response.write(shlex.quote(str(out / "camera.o")) + "\n")
    for path in dependency_paths(out / "preflight.d"):
        if not path.is_relative_to(out):
            bindings[str(path)] = sha(path)
            retained = out / "source-snapshot" / path.relative_to(PRIMARY) if path.is_relative_to(PRIMARY) else out / "source-snapshot/external" / path.name
            retained.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, retained)
    import_lists = [PRIMARY / "port/android/host_imports.list", PRIMARY / "build/macos/guest/gen/posix_imports.list",
                    PRIMARY / "build/macos/guest/gen/gl_imports.list", PRIMARY / "port/macos/host_imports.list", out / "extra-imports.list"]
    for path in import_lists[:-1]:
        bindings[str(path)] = sha(path)
    for path in (PRIMARY / "tools/android_imports.py", PRIMARY / "tools/android_asm_convert.py"):
        bindings[str(path)] = sha(path)
    steps = [(["/opt/homebrew/bin/python3", str(PRIMARY / "tools/android_imports.py"), str(out / "imports.s"), *map(str, import_lists)], "imports"),
             ([str(LLVM / "clang"), "--target=aarch64-linux-android", "-c", str(out / "imports.s"), "-o", str(out / "imports.o")], "imports-assemble"),
             ([str(LLVM / "clang"), *args, *defines, "-MD"], "compile"),
             ([str(LLVM / "opt"), "-load-pass-plugin=" + str(PRIMARY / "build/macos/guest_rebase.dylib"), "-passes=halo-rebase,verify", "-S", str(out / "d3d8_gl.ll"), "-o", str(out / "d3d8_gl.rebased.ll")], "rebase"),
             ([str(LLVM / "llc"), "-O2", "-mtriple=arm64_32-apple-watchos", "-aarch64-neon-syntax=generic", "-emulated-tls", str(out / "d3d8_gl.rebased.ll"), "-o", str(out / "d3d8_gl.darwin.s")], "codegen"),
             (["/opt/homebrew/bin/python3", str(PRIMARY / "tools/android_asm_convert.py"), str(out / "d3d8_gl.darwin.s"), str(out / "d3d8_gl.s")], "assembly-convert"),
             ([str(LLVM / "clang"), "--target=aarch64-linux-android", "-c", str(out / "d3d8_gl.s"), "-o", str(out / "d3d8_gl.o")], "assemble")]
    for command, label in steps:
        run(command, label)
    link = provenance["link_command"][:]
    link[0] = str(LINKER)  # Keep the basename dispatch; never resolve its symlink.
    capture_dir = original.parent
    substitutions = {str(capture_dir / "halo_guest.elf"): str(out / "halo_guest.elf"),
                     str(capture_dir / "halo_guest.elf.map"): str(out / "halo_guest.elf.map"),
                     "@" + str(capture_dir / "halo_guest.elf.rsp"): "@" + str(out / "halo_guest.elf.rsp")}
    link = [substitutions.get(x, x) for x in link]
    bindings[str(PRIMARY / "port/android/guest/guest.ld")] = sha(PRIMARY / "port/android/guest/guest.ld")
    run(link, "link")
    if set(dependency_paths(out / "preflight.d")) != set(dependency_paths(out / "d3d8_gl.d")):
        raise ValueError("Actual compiler inputs changed from preflight")
    for filename, expected_hash in {**bindings, **object_hashes}.items():
        if sha(filename) != expected_hash:
            raise ValueError("Source/object changed while preparing: " + filename)
    for filename in bindings:
        path = Path(filename)
        if path.is_relative_to(PRIMARY) and path.suffix in (".c", ".h", ".py", ".m", ".s", ".list", ".toml", ".json"):
            retained = out / "source-snapshot" / path.relative_to(PRIMARY)
            retained.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, retained)
    depth_prep = json.loads((prior / "prepared.json").read_text())
    cameras = {c["camera"]["name"]: c["camera"] for c in depth_prep["cases"]}
    for name in ("roof-3", "roof-west-1"):
        old = json.loads((ROOT / "build/metal-poc-0.6/roof-gpu-prepared-attempt3/prepared.json").read_text())
        cameras[name] = next(c["camera"] for c in old["cases"] if c["camera"]["name"] == name)
    bindings[str(prior / "prepared.json")] = sha(prior / "prepared.json")
    bindings[str(ROOT / "build/metal-poc-0.6/roof-gpu-prepared-attempt3/prepared.json")] = sha(ROOT / "build/metal-poc-0.6/roof-gpu-prepared-attempt3/prepared.json")
    runtime_plans = []
    for index, (name, camera) in enumerate(cameras.items()):
        folder = out / "runs" / name
        (folder / "data").mkdir(parents=True); (folder / "saves").mkdir(); (folder / "screenshots").mkdir()
        maps = PRIMARY / "assets/maps"
        (folder / "data/maps").symlink_to(maps, target_is_directory=True)
        init = ROOT / "build/metal-reference-20261004/glyph-clipping-pair/angle/data/init.txt"
        shutil.copy2(init, folder / "data/init.txt"); bindings[str(init)] = sha(init)
        (folder / "data/camera.txt").write_text(camera_text(camera["pose"], camera["vertical_fov"]))
        config = f'''[network]
online=false
allow_upnp=false
join_from_clipboard=false
signalling_brokers=""
stun_servers=""
[update]
auto=false
[discord]
application_id=""
[display]
interpolation=false
direct_camera=false
high_res_hud=false
vsync=true
screen_width=640
window_scale=1
fullscreen=false
[input]
mouse_sensitivity=1e-20
[audio]
enabled=false
[bindings]
move_forward=""
move_back=""
move_left=""
move_right=""
dpad_up=""
dpad_down=""
dpad_left=""
dpad_right=""
a=""
b=""
x=""
y=""
start=""
select=""
crouch=""
zoom=""
white=""
black=""
left_trigger=""
right_trigger=""
console=""
release_mouse=""
[community_maps]
auto_download=false
[debug]
hidden_window=true
network_test=""
test_input=""
gpu_stats=false
gpu_trace_frame=480
screenshot_directory="{folder / 'screenshots'}"
screenshot_every=15
telnet_console=true
telnet_console_port={23870+index}
exit_after=30.0
'''
        (folder / "saves/config.toml").write_text(config)
        runtime_plans.append({"name": name, "requested_camera": camera, "command": [str(host_path), str(out / "halo_guest.elf")],
            "cwd": str(folder), "console_port": 23870+index, "trace_frame": 480,
            "environment_overrides": {"HALO_DATA_ROOT": str(folder / "data"), "HALO_SAVE_ROOT": str(folder / "saves"),
                "HALO_WINDOWED": "1", "HALO_SCREEN_WIDTH": "640", "HALO_WINDOW_SCALE": "1", "HALO_VOLUME": "0", "HALO_NO_AUDIO": "1"},
            "console_commands_after_player_ready": ["(show_hud false)", "(show_hud_help_text false)", "(set terminal_render false)", "(game_speed 0)", "(debug_camera_load)"],
            "settling_seconds_minimum": 2.5, "authoritative_pose": "Each original draw retains raw ILP32 render.camera/frustum and constants/viewport; requested pose is not proof of actual pose"})
    map_path = PRIMARY / "assets/maps/bloodgulch.map"
    bindings[str(map_path)] = sha(map_path)
    write(out / "prepared.json", {"kind": "roof_original_angle_diagnostic_preparation", "complete": True, "gpu_executed": False,
        "scope": "NEW current-cached ILP32 object baseline, historical shader objects, and one isolated read-only draw/camera capture shim; changed cached objects independently rebuilt byte-exact, no full current-source game rebuild",
        "historical_object_set_rebound": False, "changed_cached_objects": rebuilt,
        "changed_historical_object_count": sum(not r["added_current_graph_object"] for r in rebuilt),
        "added_current_graph_object_count": len(added),
        "historical_original_executable_retained_only_as_context": {"file": str(out / "historical-original-guest.elf"), "sha256": sha(out / "historical-original-guest.elf")},
        "original_bindings": bindings, "retained_object_bindings": object_hashes, "commands": observed,
        "artifact_bindings": {str(p): sha(p) for p in out.rglob("*") if p.is_file()}, "runtime_plans": runtime_plans,
        "guest_sha256": sha(out / "halo_guest.elf"), "host_sha256": sha(host_path), "fresh_host": fresh_host,
        "limits": ["GPU not executed", "Actual camera/frame480 not yet observed", "No original/native depth or image parity verdict",
                   "Original target resolution requested640x480; actual viewport/attachment dimensions must be verified",
                   "Camera text is only input; raw before-draw snapshots are the actual projection evidence",
                   "New camera diagnostic blob references extend original capture schema and require their own hash closure",
                   "Keyboard bindings and mouse sensitivity are controlled; live gamepad interference is not independently excluded"]})
    print(json.dumps({"prepared": str(out / "prepared.json"), "sha256": sha(out / "prepared.json"), "guest_sha256": sha(out / "halo_guest.elf"), "gpu_executed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--current-object-baseline", action="store_true", help="Explicit NEW cached-object baseline; changed inputs must rebuild byte-exact")
    args = parser.parse_args()
    try:
        prepare(args.out, args.prior, args.current_object_baseline)
    except Exception as error:
        if args.out.exists() and not (args.out / "prepared.json").exists():
            write(args.out / "preparation-failure-summary.json", {"error": str(error), "gpu_executed": False})
        raise
