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
    """Append -2, -3, ... suffix until no image-sidecar path exists."""
    def _taken(name: str) -> bool:
        return any(
            (image_dir / f"{name}.{ext}").exists()
            for ext in ("toc", "cue", "bin", "iso")
        )

    if not _taken(stem):
        return stem
    base = stem
    suffix = 2
    while _taken(stem):
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


def opus_dir(album_root: Path) -> Path:
    return album_root / "opus"


def alac_dir(album_root: Path) -> Path:
    return album_root / "alac"


def aac_dir(album_root: Path) -> Path:
    return album_root / "m4a"


def wav_dir(album_root: Path) -> Path:
    return album_root / "wav"


def prune_empty_dirs(start: Path, stop_at: Path) -> None:
    """Remove empty directories from *start* up to (but not including) *stop_at*."""
    current = start
    while current != stop_at and str(current).startswith(str(stop_at)):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
