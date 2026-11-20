"""Tools must find the main checkout's game data without knowing its name."""
from pathlib import Path
import tempfile
import unittest

from tools.primary_checkout import primary_checkout


class PrimaryCheckoutTests(unittest.TestCase):
    def test_main_checkout_is_its_own_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / '.git').mkdir()
            self.assertEqual(primary_checkout(root), root)

    def test_source_tree_without_git_is_its_own_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            self.assertEqual(primary_checkout(root), root)

    def test_worktree_finds_a_main_checkout_of_any_name_and_depth(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder).resolve()
            main = base / 'renamed-checkout'
            worktree = base / 'worktrees/nested/topic'
            (main / '.git/worktrees/topic').mkdir(parents=True)
            worktree.mkdir(parents=True)
            (worktree / '.git').write_text(f"gitdir: {main / '.git/worktrees/topic'}\n")
            self.assertEqual(primary_checkout(worktree), main)


if __name__ == '__main__':
    unittest.main()
