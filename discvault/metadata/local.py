"""Local CDDB cache provider (~/.cddb/)."""
from __future__ import annotations

import os
from pathlib import Path

from .types import DiscInfo, Metadata
from .gnudb import parse_cddb_record


_CDDB_CACHE_DIR = Path.home() / ".cddb"
_CATEGORIES = [
    "rock", "pop", "jazz", "classical", "blues", "country", "folk",
    "newage", "reggae", "soundtrack", "misc", "data",
]


def lookup(disc_info: DiscInfo, debug: bool = False) -> list[Metadata]:
    """Search local CDDB cache. Returns list of Metadata candidates."""
    if not disc_info.freedb_disc_id:
        return []
    results: list[Metadata] = []
    disc_id = disc_info.freedb_disc_id

    if _CDDB_CACHE_DIR.is_dir():
        for category_dir in _CDDB_CACHE_DIR.iterdir():
            if not category_dir.is_dir():
                continue
            candidate = category_dir / disc_id
            if candidate.is_file():
                try:
                    text = candidate.read_text(errors="replace")
                    meta = parse_cddb_record(text, source="LocalCDDB")
                    if meta and meta not in results:
                        results.append(meta)
                except Exception as exc:
                    if debug:
                        print(f"[metadata-debug] Local CDDB read error ({candidate}): {exc}")

    return results


def save(disc_id: str, category: str, record_text: str) -> None:
    """Save a CDDB record to the local cache."""
    cache_dir = _CDDB_CACHE_DIR / category
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / disc_id).write_text(record_text)
