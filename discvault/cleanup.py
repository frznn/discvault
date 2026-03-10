"""Cleanup manager: tracks created files/dirs for removal on abort."""
from __future__ import annotations

import shutil
from pathlib import Path


class Cleanup:
    """
    Tracks files and directories created during a run so they can be
    removed if the operation is aborted or fails.
    """

    def __init__(self) -> None:
        self._files: list[Path] = []
        self._dirs: list[Path] = []

    def track_file(self, path: str | Path) -> Path:
        p = Path(path)
        self._files.append(p)
        return p

    def track_dir(self, path: str | Path) -> Path:
        p = Path(path)
        self._dirs.append(p)
        return p

    def remove_all(self) -> None:
        """Delete all tracked files and directories."""
        for f in self._files:
            try:
                if f.exists():
                    f.unlink()
            except OSError:
                pass
        # Remove dirs deepest-first
        for d in reversed(self._dirs):
            try:
                if d.exists():
                    shutil.rmtree(d)
            except OSError:
                pass
        self._files.clear()
        self._dirs.clear()

    def clear(self) -> None:
        """Forget all tracked paths without deleting them (operation succeeded)."""
        self._files.clear()
        self._dirs.clear()
