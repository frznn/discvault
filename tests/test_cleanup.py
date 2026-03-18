from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discvault.cleanup import Cleanup


class CleanupTests(unittest.TestCase):
    def test_remove_all_keeps_preexisting_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("keep")

            cleanup = Cleanup()
            cleanup.track_dir(existing)
            cleanup.remove_all()

            self.assertTrue(existing.exists())
            self.assertTrue(marker.exists())

    def test_remove_all_removes_created_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created_dir = root / "created"
            created_file = root / "created.txt"

            cleanup = Cleanup()
            cleanup.track_dir(created_dir)
            cleanup.track_file(created_file)

            created_dir.mkdir()
            created_file.write_text("temp")

            cleanup.remove_all()

            self.assertFalse(created_dir.exists())
            self.assertFalse(created_file.exists())


if __name__ == "__main__":
    unittest.main()
