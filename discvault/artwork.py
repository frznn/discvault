"""Cover-art download helpers."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import requests

from .cleanup import Cleanup
from .metadata.types import Metadata
from .metadata.sanitize import sanitize_filename

_HEADERS = {
    "User-Agent": "discvault/0.1",
    "Accept": "image/*,*/*;q=0.8",
}


def download_cover_art(
    meta: Metadata,
    album_root: Path,
    *,
    cleanup: Cleanup | None = None,
    timeout: int = 15,
    debug: bool = False,
) -> Path | None:
    """Download cover art for metadata and save it under the album root."""
    for url in _candidate_urls(meta):
        try:
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                headers=_HEADERS,
            )
            response.raise_for_status()
        except Exception as exc:
            if debug:
                print(f"[metadata-debug] Cover-art download failed ({url}): {exc}")
            continue

        content_type = response.headers.get("content-type", "").lower()
        ext = meta.cover_art_ext or _ext_from_content_type(content_type) or _ext_from_url(url)
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            ext = "jpg"
        art_path = album_root / f"cover.{ext}"
        if cleanup:
            cleanup.track_file(art_path, created=not art_path.exists())
        art_path.write_bytes(response.content)
        return art_path

    return None


def describe_cover_art(meta: Metadata, *, enabled: bool = True) -> str:
    """Return a short user-facing description of cover-art availability.

    The label is intentionally minimal: only emit something when there's
    nothing to download or when the user has turned cover art off entirely.
    The TUI hides the label otherwise, so the source name doesn't repeat
    information already visible in the candidates table.
    """
    if not enabled:
        return "disabled in Settings"
    if not _candidate_urls(meta):
        return "unavailable"
    return ""


def has_cover_art(meta: Metadata) -> bool:
    """Return True when the metadata has at least one cover-art source."""
    return bool(_candidate_urls(meta))


def primary_cover_art_url(meta: Metadata) -> str:
    """Return the best URL for previewing the cover, or "" if none."""
    urls = _candidate_urls(meta)
    return urls[0] if urls else ""


def apply_cover_art_search_result(target: Metadata, hit: Metadata) -> bool:
    """Copy cover-art-bearing identifiers from ``hit`` onto ``target`` in place.

    Returns True if any field was updated. Used by the TUI's on-demand
    "search for cover art" action: a MusicBrainz search runs against the
    selected candidate's artist/album/year, and if a hit is found we
    transplant just the IDs needed to construct a Cover Art Archive URL,
    leaving the rest of the candidate's metadata untouched.
    """
    updated = False
    if hit.cover_art_url and not target.cover_art_url:
        target.cover_art_url = hit.cover_art_url
        target.cover_art_ext = hit.cover_art_ext
        updated = True
    if hit.mb_release_id and not target.mb_release_id:
        target.mb_release_id = hit.mb_release_id
        updated = True
    if hit.mb_release_group_id and not target.mb_release_group_id:
        target.mb_release_group_id = hit.mb_release_group_id
        updated = True
    return updated


def _candidate_urls(meta: Metadata) -> list[str]:
    urls: list[str] = []
    if meta.cover_art_url:
        urls.append(meta.cover_art_url)
    if meta.mb_release_id:
        urls.append(f"https://coverartarchive.org/release/{meta.mb_release_id}/front")
    if meta.mb_release_group_id:
        urls.append(f"https://coverartarchive.org/release-group/{meta.mb_release_group_id}/front")
    return [url for url in urls if url]


def _ext_from_content_type(content_type: str) -> str:
    if "jpeg" in content_type or "jpg" in content_type:
        return "jpg"
    if "png" in content_type:
        return "png"
    if "webp" in content_type:
        return "webp"
    return ""


def _ext_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if suffix:
        return sanitize_filename(suffix).lower()
    return ""
