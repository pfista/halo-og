"""Public build identity for browser-only Halo OG release discovery."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "pfista/halo-og"
DISCOVERY_URL = "https://api.github.com/repos/pfista/halo-og/releases?per_page=5"
DESKTOP_ASSETS = {"linux": "halo-linux-release.zip", "windows": "halo-windows-release.zip"}


def is_halo_main_ci(environment=None):
    environment = os.environ if environment is None else environment
    return (environment.get("GITHUB_REPOSITORY") == REPOSITORY and
            environment.get("GITHUB_REF") == "refs/heads/main")


def source_git_command(*arguments):
    # Actions' container checkout can belong to the host runner. Trust only
    # this explicitly selected source tree, without changing global Git config.
    return ["git", "-c", f"safe.directory={ROOT}", *arguments]


def source_identity():
    """Use the immutable commit, not the build clock or a mutable tag name."""
    try:
        sha = subprocess.check_output(source_git_command("rev-parse", "HEAD"), cwd=ROOT, text=True).strip()
        stamp = subprocess.check_output(source_git_command("show", "-s", "--format=%ct", "HEAD"), cwd=ROOT, text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or not stamp.isascii() or not stamp.isdecimal():
            return None
        date = datetime.fromtimestamp(int(stamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, subprocess.CalledProcessError, ValueError, OverflowError):
        return None
    return {"source_sha": sha, "source_date": date}


def ci_source_identity(environment=None):
    """Return a public identity only for a clean matching Halo OG main CI tree."""
    environment = os.environ if environment is None else environment
    if not is_halo_main_ci(environment):
        return None
    identity = source_identity()
    if not identity or identity["source_sha"] != environment.get("GITHUB_SHA"):
        return None
    try:
        status = subprocess.run(source_git_command("status", "--porcelain", "--untracked-files=normal"), cwd=ROOT, capture_output=True)
        if status.returncode or status.stdout:
            return None
    except OSError:
        return None
    return identity


def required_ci_source_identity(environment=None):
    """A Halo OG main CI build must fail instead of silently omitting notices."""
    identity = ci_source_identity(environment)
    if not identity and is_halo_main_ci(environment):
        raise RuntimeError("Halo OG main CI requires a clean committed source tree matching GITHUB_SHA; "
                           "release discovery cannot be disabled in a published build")
    return identity


def verify_desktop_discovery_artifact(path, platform, identity):
    """Check the collected executable, without running or installing it."""
    markers = {"source SHA": identity["source_sha"], "source date": identity["source_date"],
               "release API": DISCOVERY_URL, "update notice": "Halo OG update available",
               "download button": "Open download", "opt-out button": "Stop checking",
               "platform asset": DESKTOP_ASSETS[platform]}
    data = Path(path).read_bytes()
    missing = [name for name, value in markers.items() if value.encode("ascii") not in data]
    if missing:
        raise RuntimeError(f"Halo OG release discovery is missing from {Path(path).name}: " + ", ".join(missing))


def desktop_discovery_defines(environment=None):
    """Keep the separate upstream self-installer's build number at zero."""
    identity = required_ci_source_identity(environment)
    if not identity:
        return "-DHALO_OG_RELEASE_DISCOVERY=0"
    return ("-DHALO_OG_RELEASE_DISCOVERY=1 "
            f'-DHALO_OG_SOURCE_REVISION=\\"{identity["source_sha"]}\\" '
            f'-DHALO_OG_SOURCE_DATE=\\"{identity["source_date"]}\\"')
