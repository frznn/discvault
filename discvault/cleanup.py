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
        self._files: dict[Path, bool] = {}
        self._dirs: dict[Path, bool] = {}

    def track_file(self, path: str | Path, *, created: bool | None = None) -> Path:
        p = Path(path)
        if created is None:
            created = not p.exists()
        self._files[p] = bool(created)
        return p

    def track_dir(self, path: str | Path, *, created: bool | None = None) -> Path:
        p = Path(path)
        if created is None:
            created = not p.exists()
        self._dirs[p] = bool(created)
        return p

    def remove_all(self) -> None:
        """Delete all tracked files and directories."""
        for f, created in list(self._files.items()):
            try:
                if created and f.exists():
                    f.unlink()
            except OSError:
                pass
        # Remove dirs deepest-first
        for d, created in sorted(
            self._dirs.items(),
            key=lambda item: len(item[0].parts),
            reverse=True,
        ):
            try:
                if created and d.exists():
                    shutil.rmtree(d)
            except OSError:
                pass
        self._files.clear()
        self._dirs.clear()

    def clear(self) -> None:
        """Forget all tracked paths without deleting them (operation succeeded)."""
        self._files.clear()
        self._dirs.clear()
