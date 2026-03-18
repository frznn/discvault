"""MusicBrainz metadata provider."""
from __future__ import annotations

import requests

from .types import DiscInfo, Metadata, Track
from .sanitize import trim

_MB_BASE = "https://musicbrainz.org/ws/2"
_USER_AGENT = "discvault/0.1 ( https://github.com/frznn/discvault )"


def lookup(disc_info: DiscInfo, timeout: int = 15, debug: bool = False) -> list[Metadata]:
    """Query MusicBrainz by disc ID / TOC and return matching metadata candidates."""
    if not disc_info.mb_disc_id and not disc_info.mb_toc:
        return []

    params: dict[str, str] = {
        "inc": "artists+recordings+artist-credits+release-groups",
        "fmt": "json",
    }

    if disc_info.mb_disc_id:
        url = f"{_MB_BASE}/discid/{disc_info.mb_disc_id}"
    else:
        url = f"{_MB_BASE}/discid/-"
        params["toc"] = disc_info.mb_toc

    data = _request_json(url, params, timeout, debug, "MusicBrainz disc lookup")
    if data is None:
        return []
    return _parse_response(data, disc_info, debug)


def search_releases(
    artist: str,
    album: str,
    *,
    year: str = "",
    disc_info: DiscInfo | None = None,
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Search MusicBrainz releases by artist/album text and hydrate full release details."""
    search_artist = trim(artist)
    search_album = trim(album)
    search_year = trim(year)
    if not search_artist or not search_album:
        return []

    data = _request_json(
        f"{_MB_BASE}/release",
        {
            "query": _search_query(search_artist, search_album, search_year),
            "fmt": "json",
            "limit": "6",
        },
        timeout,
        debug,
        "MusicBrainz release search",
    )
    if data is None:
        return []

    effective_disc = disc_info or DiscInfo(device="")
    results: list[Metadata] = []
    seen_release_ids: set[str] = set()
    for release in data.get("releases", []):
        release_id = trim(str(release.get("id") or ""))
        if not release_id or release_id in seen_release_ids:
            continue
        detail = _request_json(
            f"{_MB_BASE}/release/{release_id}",
            {
                "inc": "artists+recordings+artist-credits+release-groups+media",
                "fmt": "json",
            },
            timeout,
            debug,
            f"MusicBrainz release fetch ({release_id})",
        )
        if detail is None:
            continue
        meta = _release_to_metadata(detail, effective_disc, debug)
        if meta is None or meta in results:
            continue
        results.append(meta)
        seen_release_ids.add(release_id)
    return results


def _ac_name(ac: list | None) -> str:
    if not ac:
        return ""
    return "".join((c.get("name", "") + c.get("joinphrase", "")) for c in ac)


def _parse_response(data: dict, disc_info: DiscInfo, debug: bool) -> list[Metadata]:
    releases = data.get("releases", [])
    if not releases:
        return []

    results: list[Metadata] = []
    for release in releases:
        meta = _release_to_metadata(release, disc_info, debug)
        if meta is not None:
            results.append(meta)

    return results


def _select_medium(release: dict, disc_info: DiscInfo, debug: bool) -> dict | None:
    media = release.get("media", [])
    if not media:
        return None

    if disc_info.mb_disc_id:
        for medium in media:
            if any(d.get("id") == disc_info.mb_disc_id for d in medium.get("discs", [])):
                return medium
        if debug:
            print(
                "[metadata-debug] MusicBrainz: release does not contain matching disc ID; "
                "skipping instead of guessing a medium."
            )
        return None

    if len(media) == 1:
        return media[0]

    if disc_info.track_count <= 0:
        if debug:
            print(
                "[metadata-debug] MusicBrainz: manual search result has multiple media; "
                "skipping ambiguous release."
            )
        return None

    matching_media = []
    for medium in media:
        track_count = medium.get("track-count")
        if not isinstance(track_count, int):
            track_count = len(medium.get("tracks", []))
        if track_count == disc_info.track_count:
            matching_media.append(medium)

    if len(matching_media) == 1:
        return matching_media[0]

    if debug:
        print(
            "[metadata-debug] MusicBrainz: ambiguous TOC fallback on multi-medium release; "
            "skipping release."
        )
    return None


def _release_to_metadata(release: dict, disc_info: DiscInfo, debug: bool) -> Metadata | None:
    medium = _select_medium(release, disc_info, debug)
    if medium is None:
        return None

    album_artist = trim(_ac_name(release.get("artist-credit")))
    album = trim(release.get("title", ""))
    year = ""
    date = release.get("date", "")
    if date:
        year = date.split("-")[0]
        if not year.isdigit() or len(year) != 4:
            year = ""

    tracks: list[Track] = []
    for t in medium.get("tracks", []):
        num_raw = t.get("number") or t.get("position") or ""
        try:
            num = int(str(num_raw).split("-")[0])
        except (ValueError, TypeError):
            continue
        title = trim(t.get("title", ""))
        artist = trim(_ac_name(t.get("artist-credit")))
        if artist == album_artist:
            artist = ""
        tracks.append(Track(number=num, title=title, artist=artist))

    if not album_artist and not album and not tracks:
        return None

    return Metadata(
        source="MusicBrainz",
        album_artist=album_artist,
        album=album,
        year=year,
        tracks=tracks,
        mb_release_id=str(release.get("id", "") or ""),
        mb_release_group_id=str(
            release.get("release-group", {}).get("id", "")
            if isinstance(release.get("release-group"), dict)
            else ""
        ),
    )


def _search_query(artist: str, album: str, year: str) -> str:
    query = [
        f'artist:"{_escape_query_term(artist)}"',
        f'release:"{_escape_query_term(album)}"',
    ]
    if year.isdigit() and len(year) == 4:
        query.append(f"date:{year}*")
    return " AND ".join(query)


def _escape_query_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _request_json(
    url: str,
    params: dict[str, str],
    timeout: int,
    debug: bool,
    label: str,
) -> dict | None:
    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] {label} failed: {exc}")
        return None
