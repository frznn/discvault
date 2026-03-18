"""Discogs metadata provider."""
from __future__ import annotations

import requests

from .sanitize import trim
from .types import DiscInfo, Metadata, Track

_API_BASE = "https://api.discogs.com"
_USER_AGENT = "discvault/0.1 (+https://github.com/frznn/discvault)"


def lookup(
    disc_info: DiscInfo,
    *,
    seed_candidates: list[Metadata] | None = None,
    artist: str = "",
    album: str = "",
    year: str = "",
    token: str = "",
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Search Discogs using seed metadata and return candidate releases."""
    search_terms = _search_terms(seed_candidates or [], artist=artist, album=album, year=year)
    if not search_terms:
        if debug:
            print("[metadata-debug] Discogs: no search terms available")
        return []

    headers = {"User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    results: list[Metadata] = []
    seen_ids: set[int] = set()
    for search_artist, search_album, search_year in search_terms:
        params = {
            "type": "release",
            "artist": search_artist,
            "release_title": search_album,
            "per_page": 6,
        }
        if search_year:
            params["year"] = search_year

        try:
            resp = requests.get(
                f"{_API_BASE}/database/search",
                params=params,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            if debug:
                print(f"[metadata-debug] Discogs search failed: {exc}")
            continue

        for item in data.get("results", []):
            release_id = item.get("id")
            if not isinstance(release_id, int) or release_id in seen_ids:
                continue
            meta = _fetch_release(
                release_id,
                disc_info,
                headers=headers,
                timeout=timeout,
                debug=debug,
            )
            if meta is None:
                continue
            results.append(meta)
            seen_ids.add(release_id)

    return results


def _search_terms(
    seed_candidates: list[Metadata],
    *,
    artist: str,
    album: str,
    year: str,
) -> list[tuple[str, str, str]]:
    terms: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    candidates = list(seed_candidates)
    if artist or album:
        candidates.append(
            Metadata(
                source="Manual",
                album_artist=artist,
                album=album,
                year=year,
            )
        )

    for candidate in candidates:
        artist_name = trim(candidate.album_artist)
        album_name = trim(candidate.album)
        if not artist_name or not album_name:
            continue
        search_year = candidate.year if candidate.year.isdigit() else ""
        key = (artist_name, album_name, search_year)
        if key not in seen:
            seen.add(key)
            terms.append(key)
    return terms


def _fetch_release(
    release_id: int,
    disc_info: DiscInfo,
    *,
    headers: dict[str, str],
    timeout: int,
    debug: bool,
) -> Metadata | None:
    try:
        resp = requests.get(
            f"{_API_BASE}/releases/{release_id}",
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] Discogs release fetch failed ({release_id}): {exc}")
        return None

    album_artist = trim(", ".join(artist.get("name", "") for artist in data.get("artists", [])))
    album = trim(data.get("title", ""))
    year_raw = str(data.get("year", "")).strip()
    year = year_raw if year_raw.isdigit() and len(year_raw) == 4 else ""

    tracks = _parse_tracklist(data.get("tracklist", []), fallback_artist=album_artist)
    if disc_info.track_count and tracks:
        audio_track_count = len(disc_info.audio_track_numbers) or disc_info.track_count
        if len(tracks) not in {disc_info.track_count, audio_track_count}:
            return None

    if not album_artist and not album and not tracks:
        return None

    cover_art_url = ""
    for image in data.get("images", []):
        image_type = str(image.get("type", "")).lower()
        if image_type == "primary":
            cover_art_url = str(image.get("uri", "")).strip()
            break
    if not cover_art_url:
        cover_art_url = str(data.get("thumb", "")).strip()

    return Metadata(
        source="Discogs",
        album_artist=album_artist,
        album=album,
        year=year,
        tracks=tracks,
        cover_art_url=cover_art_url,
        discogs_release_id=release_id,
    )


def _parse_tracklist(tracklist: list[dict], *, fallback_artist: str) -> list[Track]:
    tracks: list[Track] = []
    position = 0
    for entry in tracklist:
        if entry.get("type_") != "track":
            continue
        title = trim(entry.get("title", ""))
        if not title:
            continue
        position += 1
        artist = trim(", ".join(artist.get("name", "") for artist in entry.get("artists", [])))
        if artist == fallback_artist:
            artist = ""
        tracks.append(Track(number=position, title=title, artist=artist))
    return tracks
