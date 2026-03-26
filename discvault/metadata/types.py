from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Track:
    number: int
    title: str
    artist: str = ""


@dataclass
class Metadata:
    source: str
    album_artist: str
    album: str
    year: str = ""
    tracks: list[Track] = field(default_factory=list)
    cover_art_url: str = ""
    cover_art_ext: str = ""
    mb_release_id: str = ""
    mb_release_group_id: str = ""
    discogs_release_id: int = 0
    match_quality: str = ""  # disc_id | toc | search | cdtext | manual | (empty for unknown)

    def track(self, number: int) -> Track | None:
        for t in self.tracks:
            if t.number == number:
                return t
        return None

    @property
    def track_count(self) -> int:
        return len(self.tracks)


@dataclass
class DiscInfo:
    device: str
    track_count: int = 0
    track_offsets: list[int] = field(default_factory=list)  # absolute frame offsets
    leadout: int = 0
    track_modes: dict[int, str] = field(default_factory=dict)
    freedb_disc_id: str = ""
    mb_disc_id: str = ""
    mb_toc: str = ""  # "1 ntracks leadout off1 off2 ..." for MB TOC lookup

    @property
    def track_lengths(self) -> dict[int, int]:
        """Map of track_number -> length_in_seconds."""
        result: dict[int, int] = {}
        offsets = self.track_offsets
        for i, start in enumerate(offsets):
            end = offsets[i + 1] if i + 1 < len(offsets) else self.leadout
            length = (end - start) // 75
            if length >= 0:
                result[i + 1] = length
        return result

    @property
    def freedb_total_seconds(self) -> int:
        """Playing time from first track offset to leadout (for freedb query)."""
        if self.track_offsets and self.leadout:
            return (self.leadout - self.track_offsets[0]) // 75
        return 0

    @property
    def freedb_offset_string(self) -> str:
        return " ".join(str(o) for o in self.track_offsets)

    def track_mode(self, number: int) -> str:
        return self.track_modes.get(number, "audio")

    def is_audio_track(self, number: int) -> bool:
        return self.track_mode(number).lower() == "audio"

    @property
    def audio_track_numbers(self) -> list[int]:
        return [number for number in range(1, self.track_count + 1) if self.is_audio_track(number)]

    @property
    def data_track_numbers(self) -> list[int]:
        return [number for number in range(1, self.track_count + 1) if not self.is_audio_track(number)]
