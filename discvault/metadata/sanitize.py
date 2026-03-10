"""Text cleaning utilities for metadata values."""
from __future__ import annotations
import re

_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")

_GNUDB_COMPAT_PHRASES = (
    "not compatible app",
    "gnudb.org/howto.php",
    "gnudb.org-howto.php",
    "your program-app is not compatible with gnudb.org",
    "we recommend using another program",
    "submit your data to gnudb.org",
)


def trim(text: str) -> str:
    """Strip control characters, collapse whitespace."""
    text = _CTRL_RE.sub("", text)
    text = _SPACE_RE.sub(" ", text)
    return text.strip()


def is_gnudb_compat_warning(*parts: str) -> bool:
    """Return True if any part looks like a GnuDB compatibility rejection."""
    combined = " ".join(parts).lower()
    return any(phrase in combined for phrase in _GNUDB_COMPAT_PHRASES)


def sanitize_component(text: str) -> str:
    """Make text safe as a filesystem path component."""
    text = trim(text)
    # Replace path separators and broadly unsafe chars
    text = re.sub(r'[\\/:\*\?"<>|]+', "-", text)
    # Normalise dashes (collapse surrounding spaces)
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-. ")
    if text in (".", "..") or not text:
        text = "Unknown"
    return text


def sanitize_filename(text: str) -> str:
    result = sanitize_component(text)
    return result or "Unknown Track"
