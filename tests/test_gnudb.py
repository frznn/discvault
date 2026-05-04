from __future__ import annotations

import unittest

from discvault.metadata.gnudb import parse_cddb_record


class ParseCddbRecordTests(unittest.TestCase):
    def test_canonical_dtitle_and_ttitle_split_on_slash(self) -> None:
        record = (
            "DTITLE=Various / Compilation\n"
            "DYEAR=2001\n"
            "TTITLE0=First Artist / First Track\n"
            "TTITLE1=Second Artist / Second Track\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Various")
        self.assertEqual(meta.album, "Compilation")
        # DYEAR is the first-release year per GnuDB convention.
        self.assertEqual(meta.first_release_year, "2001")
        self.assertEqual(meta.year, "")
        self.assertEqual(len(meta.tracks), 2)
        self.assertEqual(meta.tracks[0].title, "First Track")
        self.assertEqual(meta.tracks[0].artist, "First Artist")
        self.assertEqual(meta.tracks[1].title, "Second Track")
        self.assertEqual(meta.tracks[1].artist, "Second Artist")

    def test_strips_redundant_artist_prefix_from_album_and_tracks(self) -> None:
        # Real-world shape observed in GnuDB cache for this CCR record.
        record = (
            "DTITLE=Creedence Clearwater Revival /"
            " Creedence Clearwater Revival - Bayou Country\n"
            "DYEAR=1969\n"
            "TTITLE0=Creedence Clearwater Revival - Born On The Bayou\n"
            "TTITLE1=Creedence Clearwater Revival - Bootleg\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Creedence Clearwater Revival")
        self.assertEqual(meta.album, "Bayou Country")
        self.assertEqual(meta.tracks[0].title, "Born On The Bayou")
        self.assertEqual(meta.tracks[0].artist, "Creedence Clearwater Revival")
        self.assertEqual(meta.tracks[1].title, "Bootleg")
        self.assertEqual(meta.tracks[1].artist, "Creedence Clearwater Revival")

    def test_legitimate_hyphen_in_track_title_is_preserved(self) -> None:
        # Track title contains " - " but the prefix does NOT match the album
        # artist, so it must not be stripped.
        record = (
            "DTITLE=Bruce Springsteen / Live 1975-85\n"
            "TTITLE0=Born In The U.S.A. - Live\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Bruce Springsteen")
        self.assertEqual(meta.album, "Live 1975-85")
        self.assertEqual(meta.tracks[0].title, "Born In The U.S.A. - Live")
        self.assertEqual(meta.tracks[0].artist, "")

    def test_strip_is_case_insensitive(self) -> None:
        record = (
            "DTITLE=The Beatles / Abbey Road\n"
            "TTITLE0=THE BEATLES - Come Together\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.tracks[0].title, "Come Together")
        self.assertEqual(meta.tracks[0].artist, "The Beatles")

    def test_falls_back_to_dartist_when_no_slash_in_dtitle(self) -> None:
        record = (
            "DTITLE=Untitled Album\n"
            "DARTIST=Some Artist\n"
            "TTITLE0=Track One\n"
        )
        meta = parse_cddb_record(record, source="GnuDB")

        self.assertIsNotNone(meta)
        assert meta is not None
        self.assertEqual(meta.album_artist, "Some Artist")
        self.assertEqual(meta.album, "Untitled Album")
        self.assertEqual(meta.tracks[0].title, "Track One")
        self.assertEqual(meta.tracks[0].artist, "")


if __name__ == "__main__":
    unittest.main()
