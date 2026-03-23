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
    """Return a short user-facing description of cover-art availability."""
    if not enabled:
        return "disabled in Settings"
    urls = _candidate_urls(meta)
    if not urls:
        return "unavailable for selected metadata"
    if meta.cover_art_url:
        return f"available from {meta.source}"
    return "available via Cover Art Archive"


def has_cover_art(meta: Metadata) -> bool:
    """Return True when the metadata has at least one cover-art source."""
    return bool(_candidate_urls(meta))


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
