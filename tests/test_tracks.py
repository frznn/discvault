from __future__ import annotations

import unittest

from discvault.metadata.types import DiscInfo, Metadata, Track
from discvault.tracks import (
    compact_track_list,
    default_selected_tracks,
    display_track_count,
    effective_audio_track_numbers,
    parse_track_spec,
    possible_data_track_numbers,
    resolve_selected_tracks,
)


class TrackSelectionTests(unittest.TestCase):
    def test_parse_track_spec(self) -> None:
        self.assertEqual(parse_track_spec("1,2,4-6"), [1, 2, 4, 5, 6])

    def test_default_selection_excludes_data_tracks(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=4, track_modes={1: "audio", 2: "audio", 3: "audio", 4: "data"})
        self.assertEqual(default_selected_tracks(disc_info), [1, 2, 3])

    def test_resolve_selected_tracks_filters_data_tracks(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=4, track_modes={4: "data"})
        self.assertEqual(resolve_selected_tracks(disc_info, [2, 4]), [2])
        self.assertEqual(compact_track_list([1, 2, 4, 5, 6]), "1-2,4-6")

    def test_effective_audio_tracks_use_metadata_hint_for_trailing_extra_track(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=13)
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=number, title=f"Track {number}") for number in range(1, 13)],
        )

        self.assertEqual(effective_audio_track_numbers(disc_info, meta), list(range(1, 13)))
        self.assertEqual(possible_data_track_numbers(disc_info, meta), [13])

    def test_resolve_selected_tracks_filters_metadata_hint_extra_track(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=13)
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=number, title=f"Track {number}") for number in range(1, 13)],
        )

        self.assertEqual(resolve_selected_tracks(disc_info, None, meta), list(range(1, 13)))
        self.assertEqual(resolve_selected_tracks(disc_info, [12, 13], meta), [12])

    def test_display_track_count_uses_data_track_hint(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=14, track_modes={14: "data"})
        self.assertEqual(display_track_count(disc_info), 13)

    def test_display_track_count_uses_mounted_data_session_hint(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=14)
        self.assertEqual(display_track_count(disc_info, has_data_session=True), 13)
        self.assertEqual(
            resolve_selected_tracks(disc_info, None, extra_track_number=14, has_data_session=True),
            list(range(1, 14)),
        )


if __name__ == "__main__":
    unittest.main()
