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
        self._prune_dirs: list[Path] = []  # removed with rmdir (safe for shared parent dirs)

    def track_file(self, path: str | Path, *, created: bool | None = None) -> Path:
        p = Path(path)
        if created is None:
            created = not p.exists()
        self._files[p] = bool(created)
        return p

    def track_prune_dir(self, path: str | Path) -> Path:
        """Track a directory for safe removal only if empty (rmdir, not rmtree).
        Use this for shared parent directories like artist folders."""
        p = Path(path)
        self._prune_dirs.append(p)
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
        # Prune empty parent dirs deepest-first (safe: rmdir fails silently if not empty)
        for d in sorted(self._prune_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        self._prune_dirs.clear()

    def pending_paths(self) -> list[Path]:
        """Return all paths that would be deleted by remove_all(), sorted."""
        result = [d for d, created in self._dirs.items() if created]
        result += [f for f, created in self._files.items() if created]
        return sorted(set(result))

    def clear(self) -> None:
        """Forget all tracked paths without deleting them (operation succeeded)."""
        self._files.clear()
        self._dirs.clear()
        self._prune_dirs.clear()
