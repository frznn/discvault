"""Helpers for selecting disc tracks."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .metadata.types import DiscInfo

if TYPE_CHECKING:
    from .metadata.types import Metadata


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


def metadata_audio_track_count_hint(
    disc_info: DiscInfo,
    meta: "Metadata | None" = None,
) -> int | None:
    if meta is None or disc_info.track_count <= 0:
        return None

    track_numbers = sorted(
        {
            track.number
            for track in meta.tracks
            if 1 <= track.number <= disc_info.track_count
        }
    )
    if not track_numbers:
        return None

    highest = track_numbers[-1]
    if highest >= disc_info.track_count:
        return None

    if track_numbers == list(range(1, highest + 1)):
        return highest

    if 0 < meta.track_count < disc_info.track_count:
        return meta.track_count

    return None


def effective_audio_track_numbers(
    disc_info: DiscInfo,
    meta: "Metadata | None" = None,
    *,
    extra_track_number: int | None = None,
    has_data_session: bool = False,
) -> list[int]:
    if disc_info.track_modes:
        return disc_info.audio_track_numbers

    hinted_count = metadata_audio_track_count_hint(disc_info, meta)
    if hinted_count is not None:
        return list(range(1, hinted_count + 1))

    if extra_track_number is not None and 1 < extra_track_number <= disc_info.track_count:
        return list(range(1, extra_track_number))

    if has_data_session and disc_info.track_count > 1:
        return list(range(1, disc_info.track_count))

    return list(range(1, disc_info.track_count + 1))


def possible_data_track_numbers(
    disc_info: DiscInfo,
    meta: "Metadata | None" = None,
    *,
    extra_track_number: int | None = None,
    has_data_session: bool = False,
) -> list[int]:
    if disc_info.track_modes:
        return disc_info.data_track_numbers

    audio_tracks = effective_audio_track_numbers(
        disc_info,
        meta,
        extra_track_number=extra_track_number,
        has_data_session=has_data_session,
    )
    if len(audio_tracks) >= disc_info.track_count:
        return []

    last_audio = audio_tracks[-1] if audio_tracks else 0
    return list(range(last_audio + 1, disc_info.track_count + 1))


def default_selected_tracks(
    disc_info: DiscInfo,
    meta: "Metadata | None" = None,
    *,
    extra_track_number: int | None = None,
    has_data_session: bool = False,
) -> list[int]:
    return effective_audio_track_numbers(
        disc_info,
        meta,
        extra_track_number=extra_track_number,
        has_data_session=has_data_session,
    )


def resolve_selected_tracks(
    disc_info: DiscInfo,
    requested_tracks: list[int] | None,
    meta: "Metadata | None" = None,
    *,
    extra_track_number: int | None = None,
    has_data_session: bool = False,
) -> list[int]:
    audio_tracks = set(
        effective_audio_track_numbers(
            disc_info,
            meta,
            extra_track_number=extra_track_number,
            has_data_session=has_data_session,
        )
    )
    if requested_tracks is None:
        return sorted(audio_tracks)
    return sorted(
        {
            track
            for track in requested_tracks
            if 1 <= track <= disc_info.track_count and track in audio_tracks
        }
    )


def display_track_count(
    disc_info: DiscInfo,
    meta: "Metadata | None" = None,
    *,
    extra_track_number: int | None = None,
    has_data_session: bool = False,
) -> int:
    return len(
        effective_audio_track_numbers(
            disc_info,
            meta,
            extra_track_number=extra_track_number,
            has_data_session=has_data_session,
        )
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
