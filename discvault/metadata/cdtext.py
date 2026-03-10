"""CD-Text metadata provider via cd-info."""
from __future__ import annotations

import subprocess

from .types import DiscInfo, Metadata, Track
from .sanitize import trim


def lookup(disc_info: DiscInfo, debug: bool = False) -> list[Metadata]:
    """Extract CD-Text from disc via cd-info. Returns list with 0 or 1 Metadata."""
    try:
        result = subprocess.run(
            ["cd-info", "--no-header", "--no-device-info", "--no-disc-mode",
             "--cdtext", disc_info.device],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = result.stdout
    except FileNotFoundError:
        if debug:
            print("[metadata-debug] cd-info not found")
        return []
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] cd-info failed: {exc}")
        return []

    meta = _parse_cdinfo_output(output)
    if meta:
        return [meta]
    return []


def _parse_cdinfo_output(text: str) -> Metadata | None:
    album_artist = ""
    album = ""
    tracks: list[Track] = []

    current_track: int | None = None
    track_title: dict[int, str] = {}
    track_artist: dict[int, str] = {}

    for line in text.splitlines():
        line = line.rstrip()

        # Track header: "Track  1"
        if line.strip().startswith("Track") and not line.strip().startswith("Tracks"):
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1].isdigit():
                current_track = int(parts[1])
            continue

        stripped = line.lstrip()

        if stripped.startswith("CD-TEXT for Disc:") or stripped.startswith("CD-TEXT:"):
            current_track = None
            continue

        if "TITLE:" in stripped:
            value = trim(stripped.split("TITLE:", 1)[1])
            if current_track is None:
                album = value
            else:
                track_title[current_track] = value
        elif "PERFORMER:" in stripped:
            value = trim(stripped.split("PERFORMER:", 1)[1])
            if current_track is None:
                album_artist = value
            else:
                track_artist[current_track] = value

    if not album and not album_artist and not track_title:
        return None

    for num, title in sorted(track_title.items()):
        artist = track_artist.get(num, "")
        tracks.append(Track(number=num, title=title, artist=artist))

    if not album_artist and not album and not tracks:
        return None

    return Metadata(
        source="CD-Text",
        album_artist=album_artist,
        album=album,
        year="",
        tracks=tracks,
    )
