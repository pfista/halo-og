"""Read the product version shared with native game code."""

from pathlib import Path
import re


VERSION_HEADER = Path(__file__).resolve().parents[1] / "port/linux/include/halo_og_version.h"


def read_version():
    versions = re.findall(
        r'^[ \t]*#define[ \t]+HALO_OG_VERSION[ \t]+"(\d+(?:\.\d+){0,2})"[ \t]*$',
        VERSION_HEADER.read_text(encoding="utf-8"), re.MULTILINE)
    if len(versions) != 1:
        raise RuntimeError(f"Expected one numeric HALO_OG_VERSION in {VERSION_HEADER}")
    return versions[0]


def require_version(version):
    expected = read_version()
    if version != expected:
        raise RuntimeError(
            f"Package version {version!r} must match HALO_OG_VERSION {expected!r}. "
            "Edit port/linux/include/halo_og_version.h and rebuild instead of overriding --version.")
