#!/usr/bin/env python3
"""Run offline Android Timer Audio fixtures with real JSON-Java and the JNI helper.

The JVM suite requires JDK 17+ and Linux renameat2. Default execution makes no
network requests; supply --json-jar or explicitly --fetch-json for CI setup.
The SHA-256-pinned Maven test dependency is never packaged in the Android app.
"""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "port/android/app/src/main/java/com/halo/decomp/TimerAudio.java"
JNI = ROOT / "port/android/host/host_timer_audio.c"
FIXTURE = ROOT / "port/android/tests/TimerAudioTest.java"
JSON_URL = "https://repo.maven.apache.org/maven2/org/json/json/20240303/json-20240303.jar"
JSON_SHA256 = "3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed"
MAX_JSON_BYTES = 1048576


def compile_native(output, *extra):
    compiler = shutil.which("cc") or shutil.which("clang")
    if not compiler:
        raise RuntimeError("A C compiler is required for the JNI helper fixtures")
    subprocess.run([compiler, "-shared", "-fPIC", "-D_GNU_SOURCE", "-Wall", "-Wextra", *extra,
                    str(JNI), "-o", str(output)], check=True)


def native_fixtures(output):
    library = output / "publish-host.so"
    compile_native(library, "-DHALO_TIMER_AUDIO_HOST_TEST")
    publish = ctypes.CDLL(str(library)).halo_android_timer_audio_publish
    publish.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    publish.restype = ctypes.c_int
    source, target = output / "source", output / "target"
    source.mkdir()
    (source / "recording").write_bytes(b"synthetic")
    result = publish(os.fsencode(source), os.fsencode(target))
    if not sys.platform.startswith("linux"):
        assert result == 0 and (source / "recording").read_bytes() == b"synthetic" and not target.exists()
        print("SKIP: successful native renameat2 fixtures require Linux; unsupported-platform preservation passed.")
        return
    assert result == 1 and not source.exists() and (target / "recording").read_bytes() == b"synthetic"
    source.mkdir()
    (source / "recording").write_bytes(b"new")
    empty = output / "existing-empty"
    empty.mkdir()
    for destination in (target, empty):
        assert publish(os.fsencode(source), os.fsencode(destination)) == 0
        assert (source / "recording").read_bytes() == b"new"
    assert not list(empty.iterdir())
    existing_file = output / "existing-file"
    existing_file.write_bytes(b"user")
    assert publish(os.fsencode(source), os.fsencode(existing_file)) == 0
    assert existing_file.read_bytes() == b"user"
    linked = output / "existing-link"
    linked.symlink_to(target, target_is_directory=True)
    assert publish(os.fsencode(source), os.fsencode(linked)) == 0 and linked.is_symlink()
    print("Android native renameat2 success and existing folder/file/link preservation fixtures passed.")


def find_jdk():
    javac = shutil.which("javac")
    if not javac:
        return None
    result = subprocess.run([javac, "-version"], capture_output=True, text=True)
    if result.returncode:
        return None
    root = Path(javac).resolve().parent.parent
    if not (root / "include/jni.h").is_file() and os.environ.get("JAVA_HOME"):
        root = Path(os.environ["JAVA_HOME"])
    if not (root / "include/jni.h").is_file():
        return None
    return root


def json_jar(args, output):
    jar = args.json_jar or output / "json-20240303.jar"
    if not jar.exists() and args.fetch_json:
        # This explicit test-setup switch is separate from the offline suite.
        with urllib.request.urlopen(JSON_URL, timeout=30) as response:
            data = response.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES or hashlib.sha256(data).hexdigest() != JSON_SHA256:
            raise RuntimeError("The JSON-Java test dependency failed its pinned SHA-256")
        jar.parent.mkdir(parents=True, exist_ok=True)
        with jar.open("xb") as stream:
            stream.write(data)
    if not jar.is_file() or jar.is_symlink() or jar.stat().st_size > MAX_JSON_BYTES:
        raise RuntimeError("Supply the pinned JSON-Java 20240303 JAR with --json-jar, or explicitly use --fetch-json")
    if hashlib.sha256(jar.read_bytes()).hexdigest() != JSON_SHA256:
        raise RuntimeError("The JSON-Java test dependency failed its pinned SHA-256")
    return jar.resolve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-jar", type=Path, help="Existing official JSON-Java 20240303 JAR; its exact SHA-256 is checked")
    parser.add_argument("--fetch-json", action="store_true", help="Explicitly fetch the checksum-pinned Maven test dependency before the offline suite")
    parser.add_argument("--require-jdk", action="store_true", help="Fail if real Linux/JDK/JNI runtime fixtures cannot run (for Android CI)")
    args = parser.parse_args()
    output = ROOT / "build/android/tests/timer-audio"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-", dir=output) as temporary:
        native_fixtures(Path(temporary))
    jdk = find_jdk()
    if not jdk or not sys.platform.startswith("linux"):
        message = "Real Android Timer Audio JVM/JNI fixtures require Linux and JDK 17+; no Java suite was run."
        if args.require_jdk:
            raise RuntimeError(message)
        print("SKIP: " + message)
        return
    jar = json_jar(args, output)
    classes = output / "classes"
    classes.mkdir(exist_ok=True)
    subprocess.run([str(jdk / "bin/javac"), "--release", "17", "-Xlint:all", "-cp", str(jar),
                    "-d", str(classes), str(SOURCE), str(FIXTURE)], check=True)
    native = output / "publish-jni.so"
    compile_native(native, "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux"))
    with tempfile.TemporaryDirectory(prefix="jvm-", dir=output) as temporary:
        subprocess.run([str(jdk / "bin/java"), "-ea", "-cp", str(classes) + os.pathsep + str(jar),
                        "com.halo.decomp.TimerAudioTest", temporary, str(native)], check=True, timeout=30)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print("Android Timer Audio verification failed: " + str(error), file=sys.stderr)
        sys.exit(1)
