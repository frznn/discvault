from __future__ import annotations

import unittest

from discvault.metadata.types import DiscInfo
from discvault.tracks import compact_track_list, default_selected_tracks, parse_track_spec, resolve_selected_tracks


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


if __name__ == "__main__":
    unittest.main()
