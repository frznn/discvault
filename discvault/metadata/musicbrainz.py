"""MusicBrainz metadata provider."""
from __future__ import annotations

import requests

from .types import DiscInfo, Metadata, Track
from .sanitize import trim, is_gnudb_compat_warning

_MB_BASE = "https://musicbrainz.org/ws/2"
_USER_AGENT = "discvault/0.1 ( https://github.com/frznn/discvault )"


def lookup(disc_info: DiscInfo, timeout: int = 15, debug: bool = False) -> list[Metadata]:
    """Query MusicBrainz and return all matching Metadata candidates."""
    if not disc_info.mb_disc_id and not disc_info.mb_toc:
        return []

    params: dict[str, str] = {
        "inc": "artists+recordings+artist-credits",
        "fmt": "json",
    }

    if disc_info.mb_disc_id:
        url = f"{_MB_BASE}/discid/{disc_info.mb_disc_id}"
    else:
        url = f"{_MB_BASE}/discid/-"
        params["toc"] = disc_info.mb_toc

    try:
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] MusicBrainz request failed: {exc}")
        return []

    return _parse_response(data, disc_info.mb_disc_id, debug)


def _ac_name(ac: list | None) -> str:
    if not ac:
        return ""
    return "".join((c.get("name", "") + c.get("joinphrase", "")) for c in ac)


def _parse_response(data: dict, disc_id: str, debug: bool) -> list[Metadata]:
    releases = data.get("releases", [])
    if not releases:
        return []

    results: list[Metadata] = []
    for release in releases:
        # Find the medium that contains our disc ID
        medium = None
        for m in release.get("media", []):
            if disc_id and any(d.get("id") == disc_id for d in m.get("discs", [])):
                medium = m
                break
        if medium is None:
            media = release.get("media", [])
            medium = media[0] if media else None
        if medium is None:
            continue

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
            # Omit track artist if same as album artist
            if artist == album_artist:
                artist = ""
            tracks.append(Track(number=num, title=title, artist=artist))

        if not album_artist and not album and not tracks:
            continue

        results.append(Metadata(
            source="MusicBrainz",
            album_artist=album_artist,
            album=album,
            year=year,
            tracks=tracks,
        ))

    return results
