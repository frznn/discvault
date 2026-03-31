"""Discogs metadata provider."""
from __future__ import annotations

import requests

from .search import combine_search_text
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
    query: str = "",
    token: str = "",
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Search Discogs using seed metadata and return candidate releases."""
    search_plans = _search_plans(
        seed_candidates or [],
        artist=artist,
        album=album,
        year=year,
        query=query,
    )
    if not search_plans:
        if debug:
            print("[metadata-debug] Discogs: no search terms available")
        return []

    headers = {"User-Agent": _USER_AGENT}
    if token:
        headers["Authorization"] = f"Discogs token={token}"

    results: list[Metadata] = []
    seen_ids: set[int] = set()
    for params, allow_inexact_track_count in search_plans:
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
                allow_inexact_track_count=allow_inexact_track_count,
            )
            if meta is None:
                continue
            results.append(meta)
            seen_ids.add(release_id)

    return results


def _search_plans(
    seed_candidates: list[Metadata],
    *,
    artist: str,
    album: str,
    year: str,
    query: str,
) -> list[tuple[dict[str, str | int], bool]]:
    plans: list[tuple[dict[str, str | int], bool]] = []
    seen: set[tuple[tuple[tuple[str, str], ...], bool]] = set()

    def _add(params: dict[str, str | int], *, allow_inexact_track_count: bool) -> None:
        key = (
            tuple(sorted((str(name), str(value)) for name, value in params.items())),
            allow_inexact_track_count,
        )
        if key not in seen:
            seen.add(key)
            plans.append((params, allow_inexact_track_count))

    free_form_query = combine_search_text(query, artist=artist, album=album, year=year)
    if free_form_query:
        _add(
            {
                "type": "release",
                "q": free_form_query,
                "per_page": 10,
            },
            allow_inexact_track_count=True,
        )

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
        if not artist_name and not album_name:
            continue
        search_year = candidate.year if candidate.year.isdigit() else ""
        full_text = combine_search_text(
            "",
            artist=artist_name,
            album=album_name,
            year=search_year,
        )
        if full_text:
            _add(
                {
                    "type": "release",
                    "q": full_text,
                    "per_page": 10,
                },
                allow_inexact_track_count=True,
            )

        params: dict[str, str | int] = {
            "type": "release",
            "per_page": 6,
        }
        if artist_name:
            params["artist"] = artist_name
        if album_name:
            params["release_title"] = album_name
        if search_year:
            params["year"] = search_year
        if "artist" in params or "release_title" in params:
            _add(params, allow_inexact_track_count=False)

    return plans


def _fetch_release(
    release_id: int,
    disc_info: DiscInfo,
    *,
    headers: dict[str, str],
    timeout: int,
    debug: bool,
    allow_inexact_track_count: bool,
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
        if not allow_inexact_track_count and len(tracks) not in {disc_info.track_count, audio_track_count}:
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
        match_quality="search",
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
