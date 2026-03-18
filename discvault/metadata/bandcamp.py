"""Bandcamp metadata import by album URL."""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import urlparse

import requests

from .sanitize import trim
from .types import DiscInfo, Metadata, Track

_USER_AGENT = "discvault/0.1 (+https://github.com/frznn/discvault)"
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_TRALBUM_ATTR_RE = re.compile(
    r'data-tralbum=(?P<quote>["\'])(?P<data>.*?)(?P=quote)',
    re.IGNORECASE | re.DOTALL,
)
_META_TAG_RE = re.compile(
    r"<meta\b(?P<attrs>[^>]+?)(?:/?>)",
    re.IGNORECASE | re.DOTALL,
)
_ATTR_RE = re.compile(r'([:\w-]+)\s*=\s*(["\'])(.*?)\2', re.DOTALL)
_OG_TITLE_SPLIT_RE = re.compile(r"^(?P<album>.+?),\s+by\s+(?P<artist>.+)$", re.IGNORECASE)
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def lookup_url(
    url: str,
    *,
    disc_info: DiscInfo | None = None,
    timeout: int = 15,
    debug: bool = False,
) -> list[Metadata]:
    """Fetch and parse metadata from a Bandcamp album URL."""
    normalized = _normalize_url(url)
    if not normalized:
        if debug:
            print(f"[metadata-debug] Bandcamp URL rejected: {url!r}")
        return []

    try:
        response = requests.get(
            normalized,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] Bandcamp request failed ({normalized}): {exc}")
        return []

    meta = _parse_html(
        response.text,
        disc_info=disc_info or DiscInfo(device=""),
        debug=debug,
    )
    return [meta] if meta else []


def _normalize_url(url: str) -> str:
    candidate = trim(url)
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if parsed.scheme not in {"http", "https"} or not host.endswith("bandcamp.com"):
        return ""
    if not parsed.path or parsed.path == "/":
        return ""
    return parsed._replace(fragment="").geturl()


def _parse_html(html: str, *, disc_info: DiscInfo, debug: bool) -> Metadata | None:
    parts = {
        "album_artist": "",
        "album": "",
        "year": "",
        "cover_art_url": "",
        "tracks": [],
    }

    _merge_parts(parts, _parse_tralbum_parts(html), prefer_tracks=True)
    _merge_parts(parts, _parse_json_ld_parts(html), prefer_tracks=False)
    _merge_parts(parts, _parse_meta_parts(html), prefer_tracks=False)

    tracks: list[Track] = parts["tracks"]
    if disc_info.track_count and tracks:
        expected = {disc_info.track_count}
        audio_track_count = len(disc_info.audio_track_numbers)
        if audio_track_count:
            expected.add(audio_track_count)
        if len(tracks) not in expected and debug:
            print(
                "[metadata-debug] Bandcamp track count mismatch: "
                f"page has {len(tracks)} tracks, disc expects {sorted(expected)}"
            )

    if not parts["album_artist"] and not parts["album"] and not tracks:
        return None

    return Metadata(
        source="Bandcamp",
        album_artist=parts["album_artist"],
        album=parts["album"],
        year=parts["year"],
        tracks=tracks,
        cover_art_url=parts["cover_art_url"],
    )


def _merge_parts(base: dict, incoming: dict, *, prefer_tracks: bool) -> None:
    for key in ("album_artist", "album", "year", "cover_art_url"):
        if not base[key] and incoming.get(key):
            base[key] = incoming[key]
    incoming_tracks = incoming.get("tracks") or []
    if incoming_tracks and (prefer_tracks or not base["tracks"]):
        base["tracks"] = incoming_tracks


def _parse_json_ld_parts(html: str) -> dict:
    parts = {
        "album_artist": "",
        "album": "",
        "year": "",
        "cover_art_url": "",
        "tracks": [],
    }
    for raw in _JSON_LD_RE.findall(html):
        for item in _json_ld_items(raw):
            type_name = _lower_types(item)
            if "musicalbum" not in type_name and "album" not in type_name:
                continue
            album_artist = _extract_name(item.get("byArtist") or item.get("author"))
            album = trim(str(item.get("name") or ""))
            year = _extract_year(str(item.get("datePublished") or item.get("dateCreated") or ""))
            cover_art_url = _extract_url(item.get("image"))
            tracks = _parse_schema_tracks(
                item.get("track"),
                fallback_artist=album_artist,
            )
            return {
                "album_artist": album_artist,
                "album": album,
                "year": year,
                "cover_art_url": cover_art_url,
                "tracks": tracks,
            }
    return parts


def _json_ld_items(raw: str) -> list[dict]:
    text = raw.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items: list[dict] = []
    if isinstance(data, dict):
        if isinstance(data.get("@graph"), list):
            items.extend(entry for entry in data["@graph"] if isinstance(entry, dict))
        items.append(data)
    elif isinstance(data, list):
        items.extend(entry for entry in data if isinstance(entry, dict))
    return items


def _lower_types(item: dict) -> set[str]:
    raw_type = item.get("@type", [])
    if isinstance(raw_type, str):
        return {raw_type.lower()}
    if isinstance(raw_type, list):
        return {str(entry).lower() for entry in raw_type}
    return set()


def _parse_schema_tracks(raw_tracks: object, *, fallback_artist: str) -> list[Track]:
    if isinstance(raw_tracks, dict) and isinstance(raw_tracks.get("itemListElement"), list):
        raw_tracks = raw_tracks["itemListElement"]
    if not isinstance(raw_tracks, list):
        return []

    tracks: list[Track] = []
    for index, item in enumerate(raw_tracks, start=1):
        item_position = index
        if isinstance(item, dict):
            item_position = _as_int(item.get("position"), index)
        entry = item.get("item") if isinstance(item, dict) and isinstance(item.get("item"), dict) else item
        if not isinstance(entry, dict):
            continue
        title = trim(str(entry.get("name") or ""))
        if not title:
            continue
        position = _as_int(entry.get("position"), item_position)
        artist = _extract_name(entry.get("byArtist") or entry.get("author"))
        if artist == fallback_artist:
            artist = ""
        tracks.append(Track(number=position, title=title, artist=artist))
    return tracks


def _parse_tralbum_parts(html: str) -> dict:
    match = _TRALBUM_ATTR_RE.search(html)
    if not match:
        return {
            "album_artist": "",
            "album": "",
            "year": "",
            "cover_art_url": "",
            "tracks": [],
        }

    raw = unescape(match.group("data")).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "album_artist": "",
            "album": "",
            "year": "",
            "cover_art_url": "",
            "tracks": [],
        }

    current = data.get("current", {}) if isinstance(data.get("current"), dict) else {}
    album_artist = trim(str(data.get("artist") or data.get("band_name") or ""))
    album = trim(str(current.get("title") or data.get("album_title") or data.get("tracktitle") or ""))
    year = _extract_year(str(current.get("release_date") or data.get("album_release_date") or ""))
    cover_art_url = trim(str(data.get("artFullsizeUrl") or ""))

    tracks: list[Track] = []
    raw_tracks = data.get("trackinfo", [])
    if isinstance(raw_tracks, list):
        for index, item in enumerate(raw_tracks, start=1):
            if not isinstance(item, dict):
                continue
            title = trim(str(item.get("title") or ""))
            if not title:
                continue
            artist = trim(str(item.get("artist") or ""))
            if artist == album_artist:
                artist = ""
            tracks.append(
                Track(
                    number=_as_int(item.get("track_num"), index),
                    title=title,
                    artist=artist,
                )
            )

    return {
        "album_artist": album_artist,
        "album": album,
        "year": year,
        "cover_art_url": cover_art_url,
        "tracks": tracks,
    }


def _parse_meta_parts(html: str) -> dict:
    og_title = _meta_content(html, "property", "og:title") or _meta_content(html, "name", "title")
    album = artist = ""
    if og_title:
        match = _OG_TITLE_SPLIT_RE.match(og_title)
        if match:
            album = trim(match.group("album"))
            artist = trim(match.group("artist"))

    year = (
        _extract_year(_meta_content(html, "itemprop", "datePublished"))
        or _extract_year(_meta_content(html, "name", "release_date"))
        or _extract_year(html)
    )

    return {
        "album_artist": artist,
        "album": album,
        "year": year,
        "cover_art_url": _meta_content(html, "property", "og:image"),
        "tracks": [],
    }


def _meta_content(html: str, attr_name: str, attr_value: str) -> str:
    wanted_name = attr_name.lower()
    wanted_value = attr_value.lower()
    for match in _META_TAG_RE.finditer(html):
        attrs = {
            key.lower(): unescape(value)
            for key, _quote, value in _ATTR_RE.findall(match.group("attrs"))
        }
        if attrs.get(wanted_name, "").lower() == wanted_value:
            return trim(attrs.get("content", ""))
    return ""


def _extract_name(value: object) -> str:
    if isinstance(value, dict):
        return trim(str(value.get("name") or ""))
    if isinstance(value, list):
        names = [_extract_name(item) for item in value]
        return trim(", ".join(name for name in names if name))
    return trim(str(value or ""))


def _extract_url(value: object) -> str:
    if isinstance(value, str):
        return trim(value)
    if isinstance(value, list):
        for item in value:
            result = _extract_url(item)
            if result:
                return result
    if isinstance(value, dict):
        return trim(str(value.get("url") or value.get("@id") or ""))
    return ""


def _extract_year(text: str) -> str:
    match = _YEAR_RE.search(text or "")
    return match.group(0) if match else ""


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
