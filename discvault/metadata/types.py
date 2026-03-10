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
