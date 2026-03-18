from __future__ import annotations

import unittest

from discvault.artwork import describe_cover_art
from discvault.metadata.types import Metadata


class ArtworkTests(unittest.TestCase):
    def test_describe_cover_art_reports_source(self) -> None:
        meta = Metadata(
            source="Discogs",
            album_artist="Artist",
            album="Album",
            cover_art_url="https://example.test/cover.jpg",
        )
        self.assertEqual(describe_cover_art(meta, enabled=True), "available from Discogs")

    def test_describe_cover_art_reports_archive_fallback(self) -> None:
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            mb_release_id="release-id",
        )
        self.assertEqual(
            describe_cover_art(meta, enabled=True),
            "available via Cover Art Archive",
        )

    def test_describe_cover_art_respects_disabled_flag(self) -> None:
        meta = Metadata(source="Manual", album_artist="Artist", album="Album")
        self.assertEqual(describe_cover_art(meta, enabled=False), "disabled in Settings")


if __name__ == "__main__":
    unittest.main()
