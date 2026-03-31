"""Helpers for free-form metadata search."""
from __future__ import annotations

import re

from .sanitize import trim

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
