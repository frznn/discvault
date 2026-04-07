"""MusicBrainz metadata provider."""
from __future__ import annotations

import requests

from .search import combine_search_text, extract_year, search_tokens
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
    query: str = "",
    disc_info: DiscInfo | None = None,
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Search MusicBrainz releases by artist/album text and hydrate full release details."""
    search_artist = trim(artist)
    search_album = trim(album)
    search_year = trim(year)
    search_queries = _search_queries(
        query=trim(query),
        artist=search_artist,
        album=search_album,
        year=search_year,
    )
    if not search_queries:
        return []

    effective_disc = disc_info or DiscInfo(device="")
    results: list[Metadata] = []
    seen_release_ids: set[str] = set()
    for search_query in search_queries:
        data = _request_json(
            f"{_MB_BASE}/release",
            {
                "query": search_query,
                "fmt": "json",
                "limit": "8",
            },
            timeout,
            debug,
            "MusicBrainz release search",
        )
        if data is None:
            continue

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
            meta = _release_to_metadata(detail, effective_disc, debug, match_quality="search")
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

    match_quality = "disc_id" if disc_info.mb_disc_id else "toc"
    ranked_results: list[tuple[tuple[int, ...], Metadata]] = []
    distinct_release_groups: set[tuple[str, str]] = set()
    for release in releases:
        candidate = _release_to_candidate(release, disc_info, debug, match_quality=match_quality)
        if candidate is None:
            continue
        meta, medium = candidate
        ranked_results.append((_automatic_lookup_score(release, medium, meta), meta))
        distinct_release_groups.add(_release_group_key(meta))

    if not disc_info.mb_disc_id and len(distinct_release_groups) > 1:
        if debug:
            print(
                "[metadata-debug] MusicBrainz: ambiguous TOC fallback across multiple distinct releases; "
                "skipping automatic MusicBrainz matches."
            )
        return []

    if not disc_info.mb_disc_id:
        ranked_results.sort(key=lambda item: item[0], reverse=True)

    return [meta for _, meta in ranked_results]


def _release_group_key(meta: Metadata) -> tuple[str, str]:
    group_id = trim(meta.mb_release_group_id)
    if group_id:
        return ("release-group", group_id)
    return ("release", trim(meta.album_artist).casefold() + "\0" + _normalized_release_title(meta.album))


def _normalized_release_title(value: str) -> str:
    title = trim(value).casefold()
    if len(title) >= 2 and title[0] == "[" and title[-1] == "]":
        title = trim(title[1:-1])
    return title


def _automatic_lookup_score(release: dict, medium: dict, meta: Metadata) -> tuple[int, ...]:
    release_group = release.get("release-group")
    release_group_title = ""
    if isinstance(release_group, dict):
        release_group_title = trim(str(release_group.get("title", "")))

    disc_id_count = sum(
        1
        for disc in medium.get("discs", [])
        if trim(str(disc.get("id", "")))
    )
    release_date = trim(str(release.get("date", "")))

    return (
        int(meta.match_quality == "disc_id"),
        int(disc_id_count > 0),
        int(
            bool(release_group_title)
            and _normalized_release_title(meta.album) == _normalized_release_title(release_group_title)
        ),
        _date_precision(release_date),
        int(bool(meta.year)),
        int(bool(meta.tracks)),
    )


def _date_precision(value: str) -> int:
    value = trim(value)
    if not value:
        return 0
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        return 3
    if len(value) >= 7 and value[4:5] == "-":
        return 2
    if len(value) == 4 and value.isdigit():
        return 1
    return 0


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


def _release_to_metadata(
    release: dict,
    disc_info: DiscInfo,
    debug: bool,
    *,
    match_quality: str = "",
) -> Metadata | None:
    medium = _select_medium(release, disc_info, debug)
    if medium is None:
        return None
    return _metadata_from_release_medium(release, medium, match_quality=match_quality)


def _release_to_candidate(
    release: dict,
    disc_info: DiscInfo,
    debug: bool,
    *,
    match_quality: str = "",
) -> tuple[Metadata, dict] | None:
    medium = _select_medium(release, disc_info, debug)
    if medium is None:
        return None
    meta = _metadata_from_release_medium(release, medium, match_quality=match_quality)
    if meta is None:
        return None
    return meta, medium


def _metadata_from_release_medium(
    release: dict,
    medium: dict,
    *,
    match_quality: str = "",
) -> Metadata | None:
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
        match_quality=match_quality,
    )


def _search_queries(*, query: str, artist: str, album: str, year: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    def _add(search_query: str) -> None:
        if search_query and search_query not in seen:
            seen.add(search_query)
            results.append(search_query)

    _add(_structured_search_query(artist, album, year))
    _add(_token_search_query(combine_search_text(query, artist=artist, album=album, year=year), year))
    return results


def _structured_search_query(artist: str, album: str, year: str) -> str:
    query: list[str] = []
    artist_query = _field_query("artist", artist)
    album_query = _field_query("release", album)
    if artist_query:
        query.append(artist_query)
    if album_query:
        query.append(album_query)
    if year.isdigit() and len(year) == 4:
        query.append(f"date:{year}*")
    return " AND ".join(query)


def _field_query(field: str, value: str) -> str:
    tokens = search_tokens(value)
    if not tokens:
        return ""
    escaped = " AND ".join(_escape_query_term(token) for token in tokens)
    return f"{field}:({escaped})"


def _token_search_query(text: str, year: str) -> str:
    tokens = search_tokens(text)
    extracted_year = extract_year(text)
    effective_year = year if year.isdigit() and len(year) == 4 else extracted_year
    terms = [
        _escape_query_term(token)
        for token in tokens
        if not (token.isdigit() and len(token) == 4)
    ]
    if effective_year:
        terms.append(f"date:{effective_year}*")
    return " AND ".join(terms)


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
