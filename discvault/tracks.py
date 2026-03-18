"""Helpers for selecting disc tracks."""
from __future__ import annotations

from .metadata.types import DiscInfo


def parse_track_spec(spec: str) -> list[int]:
    tracks: set[int] = set()
    for chunk in spec.split(","):
        part = chunk.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            if start > end:
                start, end = end, start
            tracks.update(range(start, end + 1))
        else:
            tracks.add(int(part))
    return sorted(tracks)


def default_selected_tracks(disc_info: DiscInfo) -> list[int]:
    audio_tracks = disc_info.audio_track_numbers
    if audio_tracks:
        return audio_tracks
    return list(range(1, disc_info.track_count + 1))


def resolve_selected_tracks(
    disc_info: DiscInfo,
    requested_tracks: list[int] | None,
) -> list[int]:
    if requested_tracks is None:
        return default_selected_tracks(disc_info)
    return sorted(
        {
            track
            for track in requested_tracks
            if 1 <= track <= disc_info.track_count and disc_info.is_audio_track(track)
        }
    )


def compact_track_list(tracks: list[int]) -> str:
    if not tracks:
        return "(none)"

    ranges: list[str] = []
    start = prev = tracks[0]
    for track in tracks[1:]:
        if track == prev + 1:
            prev = track
            continue
        ranges.append(_format_range(start, prev))
        start = prev = track
    ranges.append(_format_range(start, prev))
    return ",".join(ranges)


def _format_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"
