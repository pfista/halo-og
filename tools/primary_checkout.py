"""Locate the checkout that holds the untracked game data and Mac build.

Extracted maps (`assets/`) and Mac build products (`build/macos/`) are ignored
by git and exist once, in the main checkout. A git worktree reaches that
checkout through its `.git` file; the main checkout is its own primary. Tools
use `PRIMARY` instead of naming a checkout directory, so renaming or moving a
checkout does not break them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def primary_checkout(root=ROOT):
    """Return the main checkout that owns `root`, or `root` itself."""
    marker = root / '.git'
    if not marker.is_file():
        return root
    text = marker.read_text().strip()
    if not text.startswith('gitdir:'):
        return root
    gitdir = Path(text.split(':', 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (root / gitdir).resolve()
    # A worktree's git directory is <main checkout>/.git/worktrees/<name>.
    if gitdir.parent.name != 'worktrees' or gitdir.parents[1].name != '.git':
        return root
    return gitdir.parents[2]


PRIMARY = primary_checkout()
