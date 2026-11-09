"""Helpers for free-form metadata search."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .sanitize import trim
from .types import Metadata

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def combine_search_text(
    query: str,
    *,
    artist: str = "",
    album: str = "",
    year: str = "",
) -> str:
    """Return the explicit query, or a best-effort search string from structured fields."""
    query = trim(query)
    if query:
        return query

    parts = [trim(artist), trim(album)]
    year = trim(year)
    if year.isdigit() and len(year) == 4:
        parts.append(year)
    return trim(" ".join(part for part in parts if part))


def search_tokens(text: str) -> list[str]:
    """Split free-form search text into useful deduplicated tokens."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(trim(text)):
        token = trim(raw)
        if not token:
            continue
        normalized = token.casefold()
        if len(normalized) == 1 and not normalized.isdigit():
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        tokens.append(token)
    return tokens


def extract_year(text: str) -> str:
    """Return the first 4-digit year found in free-form text."""
    match = _YEAR_RE.search(trim(text))
    return match.group(0) if match else ""


def normalize_text(value: str) -> str:
    """Casefold, strip accents and reduce to space-joined word tokens."""
    stripped = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(search_tokens(stripped.casefold()))


def _contains(field_value: str, wanted: str) -> bool:
    """Whole-token-sequence substring match on normalized text."""
    wanted_norm = normalize_text(wanted)
    if not wanted_norm:
        return True
    return f" {wanted_norm} " in f" {normalize_text(field_value)} "


def filter_candidates(
    candidates: Iterable[Metadata],
    *,
    artist: str = "",
    album: str = "",
    year: str = "",
    track_count: int = 0,
) -> list[Metadata]:
    """Keep the candidates matching every non-blank filter.

    Artist and album match case- and accent-insensitively as a contiguous run
    of whole words ("beatles" matches "The Beatles", "bea" does not). Year is
    an exact match against the release year or the first-release year. Track
    count is an exact match; a candidate with no tracklist has an unknown
    count and is kept, since dropping it would hide results for want of data.
    A blank filter (empty text, zero count) is ignored.
    """
    year = trim(year)
    kept: list[Metadata] = []
    for meta in candidates:
        if not _contains(meta.album_artist, artist):
            continue
        if not _contains(meta.album, album):
            continue
        if year and year not in (trim(meta.year)[:4], trim(meta.first_release_year)[:4]):
            continue
        if track_count > 0 and meta.track_count and meta.track_count != track_count:
            continue
        kept.append(meta)
    return kept
