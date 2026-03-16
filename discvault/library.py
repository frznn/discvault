"""Library path management and filesystem sanitization."""
from __future__ import annotations
from pathlib import Path

from .metadata.sanitize import sanitize_component, sanitize_filename


def album_root(base_dir: str, artist: str, album: str, year: str) -> Path:
    artist_dir = sanitize_component(artist)
    if year:
        album_dir = sanitize_component(f"{year}. {album}")
    else:
        album_dir = sanitize_component(album)
    return Path(base_dir) / artist_dir / album_dir


def image_stem(artist: str, album: str, year: str) -> str:
    a = sanitize_component(artist)
    al = sanitize_component(album)
    base = f"{a}-{al}-{year}" if year else f"{a}-{al}"
    return sanitize_filename(base)


def unique_image_stem(image_dir: Path, stem: str) -> str:
    """Append -2, -3, ... suffix until neither .toc nor .bin exists."""
    if not (image_dir / f"{stem}.toc").exists() and not (image_dir / f"{stem}.bin").exists():
        return stem
    base = stem
    suffix = 2
    while (image_dir / f"{stem}.toc").exists() or (image_dir / f"{stem}.bin").exists():
        stem = f"{base}-{suffix}"
        suffix += 1
    return stem


def track_filename(track_num: int, track_total: int, title: str, ext: str = "") -> str:
    width = len(str(track_total)) if track_total >= 10 else 2
    padded = str(track_num).zfill(width)
    safe_title = sanitize_filename(title)
    name = f"{padded} - {safe_title}"
    return f"{name}.{ext}" if ext else name


def image_dir(album_root: Path) -> Path:
    return album_root / "image"


def flac_dir(album_root: Path) -> Path:
    return album_root / "flac"


def mp3_dir(album_root: Path) -> Path:
    return album_root / "mp3"


def ogg_dir(album_root: Path) -> Path:
    return album_root / "ogg"


def prune_empty_dirs(start: Path, stop_at: Path) -> None:
    """Remove empty directories from *start* up to (but not including) *stop_at*."""
    current = start
    while current != stop_at and str(current).startswith(str(stop_at)):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
