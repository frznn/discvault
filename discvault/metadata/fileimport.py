"""Metadata import from local CUE/TOC/JSON/TOML files."""
from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

from .cdtext import _parse_cdrdao_toc
from .sanitize import trim
from .types import Metadata, Track


def lookup(path: str | Path, debug: bool = False) -> list[Metadata]:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        if debug:
            print(f"[metadata-debug] Imported metadata file not found: {file_path}")
        return []

    suffix = file_path.suffix.lower()
    try:
        if suffix == ".json":
            meta = _parse_mapping(json.loads(file_path.read_text()), source=file_path.name)
        elif suffix in {".toml", ".tml"}:
            meta = _parse_mapping(
                tomllib.loads(file_path.read_text()),
                source=file_path.name,
            )
        elif suffix == ".cue":
            meta = _parse_cue(file_path.read_text(errors="replace"), source=file_path.name)
        elif suffix == ".toc":
            parsed = _parse_cdrdao_toc(file_path.read_text(errors="replace"))
            meta = _with_source(parsed, file_path.name)
        else:
            if debug:
                print(f"[metadata-debug] Unsupported metadata import file type: {suffix}")
            return []
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] Failed to import metadata from {file_path}: {exc}")
        return []

    return [meta] if meta else []


def _parse_mapping(data: dict, *, source: str) -> Metadata | None:
    meta_data = data.get("metadata", data) if isinstance(data, dict) else {}
    if not isinstance(meta_data, dict):
        return None

    artist = trim(str(meta_data.get("album_artist") or meta_data.get("artist") or ""))
    album = trim(str(meta_data.get("album") or ""))
    year_raw = trim(str(meta_data.get("year") or ""))
    year = year_raw if year_raw.isdigit() and len(year_raw) == 4 else ""
    cover_art_url = trim(str(meta_data.get("cover_art_url") or ""))

    tracks: list[Track] = []
    raw_tracks = meta_data.get("tracks", [])
    if isinstance(raw_tracks, list):
        for index, item in enumerate(raw_tracks, start=1):
            if not isinstance(item, dict):
                continue
            number = int(item.get("number", index))
            title = trim(str(item.get("title") or ""))
            track_artist = trim(str(item.get("artist") or ""))
            tracks.append(Track(number=number, title=title, artist=track_artist))

    if not artist and not album and not tracks:
        return None

    return Metadata(
        source=f"Imported ({source})",
        album_artist=artist,
        album=album,
        year=year,
        tracks=tracks,
        cover_art_url=cover_art_url,
    )


def _parse_cue(text: str, *, source: str) -> Metadata | None:
    album_artist = ""
    album = ""
    tracks: list[Track] = []
    current_track: Track | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        upper = stripped.upper()
        if upper.startswith("PERFORMER "):
            value = _cue_value(stripped)
            if current_track is None:
                album_artist = value
            else:
                current_track.artist = value
            continue
        if upper.startswith("TITLE "):
            value = _cue_value(stripped)
            if current_track is None:
                album = value
            else:
                current_track.title = value
            continue
        if upper.startswith("TRACK "):
            parts = stripped.split()
            if len(parts) >= 2 and parts[1].isdigit():
                current_track = Track(number=int(parts[1]), title="", artist="")
                tracks.append(current_track)

    if not album_artist and not album and not tracks:
        return None

    for track in tracks:
        if track.artist == album_artist:
            track.artist = ""

    return Metadata(
        source=f"Imported ({source})",
        album_artist=album_artist,
        album=album,
        tracks=tracks,
    )


def _cue_value(line: str) -> str:
    _, _, rest = line.partition(" ")
    rest = rest.strip()
    if rest.startswith('"') and rest.endswith('"'):
        rest = rest[1:-1]
    return trim(rest)


def _with_source(meta: Metadata | None, source: str) -> Metadata | None:
    if meta is None:
        return None
    meta.source = f"Imported ({source})"
    return meta
