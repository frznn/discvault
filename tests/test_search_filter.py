from __future__ import annotations

import unittest

from discvault.metadata.search import filter_candidates
from discvault.metadata.types import Metadata, Track


def _meta(artist: str, album: str, year: str = "", tracks: int = 0, first: str = "") -> Metadata:
    return Metadata(
        source="t",
        album_artist=artist,
        album=album,
        year=year,
        first_release_year=first,
        tracks=[Track(number=i + 1, title=f"T{i + 1}") for i in range(tracks)],
    )


class FilterCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.beatles = _meta("The Beatles", "Abbey Road", "1969", 17)
        self.remaster = _meta("The Beatles", "Abbey Road", "2009", 17, first="1969")
        self.other = _meta("Beatles Tribute Band", "Abbey Road Live", "1999", 12)
        self.all = [self.beatles, self.remaster, self.other]

    def test_blank_filters_keep_everything(self) -> None:
        self.assertEqual(filter_candidates(self.all), self.all)

    def test_artist_is_case_and_accent_insensitive_whole_words(self) -> None:
        cands = [_meta("Beyoncé", "Lemonade"), _meta("Beyoncé Knowles-Carter", "X")]
        self.assertEqual(len(filter_candidates(cands, artist="BEYONCE")), 2)
        self.assertEqual(filter_candidates(cands, artist="Bey"), [])

    def test_album_matches_contiguous_words(self) -> None:
        self.assertEqual(
            filter_candidates(self.all, album="abbey road"), self.all
        )
        self.assertEqual(filter_candidates(self.all, album="road abbey"), [])

    def test_year_matches_release_or_first_release_year(self) -> None:
        self.assertEqual(
            filter_candidates(self.all, year="1969"), [self.beatles, self.remaster]
        )
        self.assertEqual(filter_candidates(self.all, year="2009"), [self.remaster])

    def test_track_count_is_exact_and_unknown_count_is_kept(self) -> None:
        unknown = _meta("A", "B")
        result = filter_candidates(self.all + [unknown], track_count=17)
        self.assertEqual(result, [self.beatles, self.remaster, unknown])

    def test_filters_combine(self) -> None:
        result = filter_candidates(
            self.all, artist="beatles", album="abbey road", year="1999", track_count=12
        )
        self.assertEqual(result, [self.other])


if __name__ == "__main__":
    unittest.main()
