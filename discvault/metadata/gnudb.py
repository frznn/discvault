"""GnuDB metadata providers: HTTP and CDDBP."""
from __future__ import annotations

import socket
import requests
from .types import DiscInfo, Metadata, Track
from .sanitize import trim, is_gnudb_compat_warning

_HTTP_URLS = [
    "https://gnudb.gnudb.org/~cddb/cddb.cgi",
    "http://gnudb.gnudb.org/~cddb/cddb.cgi",
]
_USER_AGENT = "discvault/0.1"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_http(
    disc_info: DiscInfo,
    hello_values: list[str],
    timeout: int = 15,
    cache_enabled: bool = False,
    debug: bool = False,
) -> list[Metadata]:
    """Query GnuDB via HTTP CGI. Returns list of Metadata candidates."""
    if not disc_info.freedb_disc_id:
        return []
    results: list[Metadata] = []
    for url in _HTTP_URLS:
        for hello in hello_values:
            meta = _http_query_and_read(
                disc_info,
                hello,
                url,
                timeout,
                cache_enabled,
                debug,
            )
            if meta and meta not in results:
                results.append(meta)
                return results  # one result per source is enough
    return results


def lookup_cddbp(
    disc_info: DiscInfo,
    hello_values: list[str],
    host: str,
    port: int,
    timeout: int = 15,
    cache_enabled: bool = False,
    debug: bool = False,
) -> list[Metadata]:
    """Query GnuDB via CDDBP TCP protocol."""
    if not disc_info.freedb_disc_id:
        return []
    results: list[Metadata] = []
    for hello in hello_values:
        meta = _cddbp_query_and_read(
            disc_info,
            hello,
            host,
            port,
            timeout,
            cache_enabled,
            debug,
        )
        if meta and meta not in results:
            results.append(meta)
            return results  # one result per source is enough
    return results


# ---------------------------------------------------------------------------
# HTTP implementation
# ---------------------------------------------------------------------------

def _http_query_and_read(
    disc_info: DiscInfo,
    hello: str,
    base_url: str,
    timeout: int,
    cache_enabled: bool,
    debug: bool,
) -> Metadata | None:
    cmd = (
        f"cddb query {disc_info.freedb_disc_id} {disc_info.track_count} "
        f"{disc_info.freedb_offset_string} {disc_info.freedb_total_seconds}"
    )
    try:
        resp = requests.get(
            base_url,
            params={"cmd": cmd, "hello": hello, "proto": "6"},
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        resp.raise_for_status()
        query_text = resp.text
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] GnuDB HTTP query failed ({base_url}): {exc}")
        return None

    if is_gnudb_compat_warning(query_text):
        if debug:
            print(f"[metadata-debug] GnuDB HTTP compat warning ({base_url})")
        return None

    category, disc_id = _parse_query_response(query_text)
    if not category or not disc_id:
        return None

    try:
        resp2 = requests.get(
            base_url,
            params={
                "cmd": f"cddb read {category} {disc_id}",
                "hello": hello,
                "proto": "6",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=timeout,
        )
        resp2.raise_for_status()
        read_text = resp2.text
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] GnuDB HTTP read failed ({base_url}): {exc}")
        return None

    if is_gnudb_compat_warning(read_text):
        return None

    lines = read_text.splitlines()
    if not lines:
        return None
    first = lines[0].split()
    if not first or first[0] not in ("210", "215"):
        return None

    record_text = "\n".join(lines[1:])
    meta = parse_cddb_record(record_text, source="GnuDB")
    if meta and cache_enabled:
        _save_cache_record(disc_id, category, record_text, debug)
    return meta


# ---------------------------------------------------------------------------
# CDDBP implementation
# ---------------------------------------------------------------------------

def _cddbp_query_and_read(
    disc_info: DiscInfo,
    hello: str,
    host: str,
    port: int,
    timeout: int,
    cache_enabled: bool,
    debug: bool,
) -> Metadata | None:
    cmd_query = (
        f"cddb query {disc_info.freedb_disc_id} {disc_info.track_count} "
        f"{disc_info.freedb_offset_string} {disc_info.freedb_total_seconds}"
    )
    commands = [
        f"cddb hello {hello}",
        "proto 6",
        cmd_query,
        "quit",
    ]
    try:
        response = _cddbp_exchange(host, port, commands, timeout)
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] GnuDB CDDBP query failed ({host}:{port}): {exc}")
        return None

    if is_gnudb_compat_warning(response):
        if debug:
            print(f"[metadata-debug] GnuDB CDDBP compat warning ({host}:{port})")
        return None

    # Find the 4th status line (banner, hello resp, proto resp, query resp)
    status_lines = [ln for ln in response.splitlines() if len(ln) >= 3 and ln[:3].isdigit()]
    if len(status_lines) < 4:
        if debug:
            print(f"[metadata-debug] GnuDB CDDBP query: unexpected response ({host}:{port})")
        return None

    query_status_line = status_lines[3]
    category, disc_id = _parse_cddbp_status(query_status_line, response, status_lines[3])
    if not category or not disc_id:
        return None

    read_commands = [
        f"cddb hello {hello}",
        "proto 6",
        f"cddb read {category} {disc_id}",
        "quit",
    ]
    try:
        read_response = _cddbp_exchange(host, port, read_commands, timeout)
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] GnuDB CDDBP read failed ({host}:{port}): {exc}")
        return None

    if is_gnudb_compat_warning(read_response):
        return None

    read_status_lines = [
        ln for ln in read_response.splitlines() if len(ln) >= 3 and ln[:3].isdigit()
    ]
    if len(read_status_lines) < 4:
        return None

    read_code = read_status_lines[3][:3]
    if read_code not in ("210", "215"):
        return None

    # Find the data lines after the status line
    all_lines = read_response.splitlines()
    status_idx = next(
        (i for i, ln in enumerate(all_lines) if ln == read_status_lines[3]), None
    )
    if status_idx is None:
        return None
    record_text = "\n".join(all_lines[status_idx + 1 :])
    meta = parse_cddb_record(record_text, source="GnuDB-CDDBP")
    if meta and cache_enabled:
        _save_cache_record(disc_id, category, record_text, debug)
    return meta


def _save_cache_record(disc_id: str, category: str, record_text: str, debug: bool) -> None:
    from . import local

    try:
        local.save(disc_id, category, record_text)
    except OSError as exc:
        if debug:
            print(f"[metadata-debug] Local CDDB cache save failed ({category}/{disc_id}): {exc}")


def _cddbp_exchange(host: str, port: int, commands: list[str], timeout: float) -> str:
    """Open a TCP connection, send commands, collect the full response."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        data = b""
        # Read welcome banner (first line)
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        # Send all commands
        payload = "\r\n".join(commands) + "\r\n"
        s.sendall(payload.encode())
        # Collect response until timeout or connection close
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        except (socket.timeout, OSError):
            pass
    return data.decode(errors="replace").replace("\r\n", "\n")


def _parse_query_response(text: str) -> tuple[str, str]:
    """Parse HTTP CDDB query response; return (category, disc_id) or ('', '')."""
    lines = text.splitlines()
    if not lines:
        return "", ""
    first = lines[0].split()
    if not first:
        return "", ""
    code = first[0]
    if code == "200" and len(first) >= 3:
        return first[1], first[2]
    if code in ("210", "211"):
        for line in lines[1:]:
            line = line.strip()
            if line == ".":
                break
            parts = line.split()
            if len(parts) >= 2:
                return parts[0], parts[1]
    return "", ""


def _parse_cddbp_status(status_line: str, full_response: str, _: str) -> tuple[str, str]:
    """Parse CDDBP query status line for category and disc_id."""
    parts = status_line.split()
    if not parts:
        return "", ""
    code = parts[0]
    if code == "200" and len(parts) >= 3:
        return parts[1], parts[2]
    if code in ("210", "211"):
        # Next non-dot line after this status line
        lines = full_response.splitlines()
        found = False
        for line in lines:
            if line == status_line:
                found = True
                continue
            if found:
                line = line.strip()
                if line == ".":
                    break
                lparts = line.split()
                if len(lparts) >= 2:
                    return lparts[0], lparts[1]
    return "", ""


# ---------------------------------------------------------------------------
# CDDB record parser (shared by HTTP and CDDBP)
# ---------------------------------------------------------------------------

def parse_cddb_record(text: str, source: str = "GnuDB") -> Metadata | None:
    """Parse a CDDB record and return a Metadata object, or None on failure."""
    dtitle = ""
    dyear = ""
    dartist = ""
    raw_tracks: dict[int, str] = {}  # 0-based index -> concatenated title

    for line in text.splitlines():
        if line == ".":
            break
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key == "DTITLE":
            dtitle += value
        elif key == "DYEAR":
            dyear += value
        elif key == "DARTIST":
            dartist += value
        elif key.startswith("TTITLE"):
            idx_str = key[6:]
            if idx_str.isdigit():
                idx = int(idx_str)
                raw_tracks[idx] = raw_tracks.get(idx, "") + value

    dtitle = trim(dtitle)
    dyear = trim(dyear)
    dartist = trim(dartist)

    if is_gnudb_compat_warning(dtitle, dartist):
        return None

    if " / " in dtitle:
        album_artist = trim(dtitle.split(" / ", 1)[0])
        album = trim(dtitle.split(" / ", 1)[1])
    else:
        album = dtitle
        album_artist = dartist

    # Some submitters redundantly prefix the album with "Artist - " on the
    # album side of DTITLE. Strip it only when the prefix matches the artist
    # we already determined, so legitimate hyphens are left untouched.
    album = _strip_artist_prefix(album, album_artist)

    year = dyear if (dyear.isdigit() and len(dyear) == 4) else ""

    tracks: list[Track] = []
    for idx, raw_title in sorted(raw_tracks.items()):
        title = trim(raw_title)
        if is_gnudb_compat_warning("", title):
            return None
        track_num = idx + 1
        if " / " in title:
            track_artist = trim(title.split(" / ", 1)[0])
            title = trim(title.split(" / ", 1)[1])
        else:
            stripped = _strip_artist_prefix(title, album_artist)
            if stripped != title:
                track_artist = album_artist
                title = stripped
            else:
                track_artist = ""
        if title:
            tracks.append(Track(number=track_num, title=title, artist=track_artist))

    if not album_artist and not album and not tracks:
        return None

    return Metadata(
        source=source,
        album_artist=album_artist,
        album=album,
        year=year,
        tracks=tracks,
    )


def _strip_artist_prefix(text: str, artist: str) -> str:
    """Strip a leading "<artist><dash>" segment from text, case-insensitively.

    Recognises ASCII " - ", en-dash " – ", and em-dash " — " separators.
    Returns the original text when the artist is empty or the prefix does
    not match, so legitimate hyphens inside titles are not touched.
    """
    text = trim(text)
    artist = trim(artist)
    if not artist or not text:
        return text
    lowered = text.casefold()
    artist_low = artist.casefold()
    for sep in (" - ", " – ", " — "):
        prefix = artist_low + sep
        if lowered.startswith(prefix):
            return trim(text[len(prefix):])
    return text


# ---------------------------------------------------------------------------
# GNUDB hello string builder
# ---------------------------------------------------------------------------

def build_hello_values(cfg_user: str, cfg_program: str, cfg_version: str) -> list[str]:
    """Return a list of 'user host program version' hello strings to try."""
    import os, socket as _socket

    default_host = _socket.gethostname()
    default_user = f"{os.environ.get('USER', 'user')}@{default_host}"

    users = [cfg_user or default_user]
    if not cfg_user:
        users.append(f"{os.environ.get('USER', 'user')}@example.com")

    programs = [cfg_program or "discvault"]
    if not cfg_program or cfg_program == "discvault":
        programs += ["asunder", "libcddb"]

    versions = [cfg_version or "1.0"]

    hellos: list[str] = []
    seen: set[str] = set()
    for u in users:
        for p in programs:
            for v in versions:
                h = f"{trim(u)} {default_host} {p} {v}"
                if h not in seen:
                    seen.add(h)
                    hellos.append(h)
    return hellos
