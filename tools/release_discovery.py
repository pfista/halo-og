"""Public build identity for browser-only Halo OG release discovery."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "pfista/halo-og"


def source_identity():
    """Use the immutable commit, not the build clock or a mutable tag name."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        stamp = subprocess.check_output(["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{40}", sha) or not stamp.isascii() or not stamp.isdecimal():
            return None
        date = datetime.fromtimestamp(int(stamp), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OSError, subprocess.CalledProcessError, ValueError, OverflowError):
        return None
    return {"source_sha": sha, "source_date": date}


def ci_source_identity(environment=None):
    """Return a public identity only for a clean matching Halo OG main CI tree."""
    environment = os.environ if environment is None else environment
    if (environment.get("GITHUB_REPOSITORY") != REPOSITORY or
            environment.get("GITHUB_REF") != "refs/heads/main"):
        return None
    identity = source_identity()
    if not identity or identity["source_sha"] != environment.get("GITHUB_SHA"):
        return None
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, capture_output=True)
        if status.returncode or status.stdout:
            return None
    except OSError:
        return None
    return identity


def desktop_discovery_defines(environment=None):
    """Keep the separate upstream self-installer's build number at zero."""
    identity = ci_source_identity(environment)
    if not identity:
        return "-DHALO_OG_RELEASE_DISCOVERY=0"
    return ("-DHALO_OG_RELEASE_DISCOVERY=1 "
            f'-DHALO_OG_SOURCE_REVISION=\\"{identity["source_sha"]}\\" '
            f'-DHALO_OG_SOURCE_DATE=\\"{identity["source_date"]}\\"')
