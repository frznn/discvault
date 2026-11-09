from __future__ import annotations

import unittest

from discvault.artwork import (
    apply_cover_art_search_result,
    describe_cover_art,
    primary_cover_art_url,
)
from discvault.metadata.types import Metadata


class ArtworkTests(unittest.TestCase):
    def test_describe_cover_art_returns_empty_when_available_from_meta(self) -> None:
        meta = Metadata(
            source="Discogs",
            album_artist="Artist",
            album="Album",
            cover_art_url="https://example.test/cover.jpg",
        )
        self.assertEqual(describe_cover_art(meta, enabled=True), "")

    def test_describe_cover_art_returns_empty_when_available_via_caa(self) -> None:
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            mb_release_id="release-id",
        )
        self.assertEqual(describe_cover_art(meta, enabled=True), "")

    def test_describe_cover_art_reports_unavailable_when_no_urls(self) -> None:
        meta = Metadata(source="GnuDB", album_artist="Artist", album="Album")
        self.assertEqual(describe_cover_art(meta, enabled=True), "unavailable")

    def test_describe_cover_art_respects_disabled_flag(self) -> None:
        meta = Metadata(source="Manual", album_artist="Artist", album="Album")
        self.assertEqual(describe_cover_art(meta, enabled=False), "disabled in Settings")


class PrimaryCoverArtUrlTests(unittest.TestCase):
    def test_returns_meta_url_when_present(self) -> None:
        meta = Metadata(
            source="Discogs",
            album_artist="A",
            album="B",
            cover_art_url="https://example.test/cover.jpg",
            mb_release_id="rel-id",
        )
        # Direct cover_art_url wins over the CAA fallback.
        self.assertEqual(primary_cover_art_url(meta), "https://example.test/cover.jpg")

    def test_returns_caa_url_when_only_mb_id_set(self) -> None:
        meta = Metadata(
            source="MusicBrainz",
            album_artist="A",
            album="B",
            mb_release_id="rel-id",
        )
        self.assertEqual(
            primary_cover_art_url(meta),
            "https://coverartarchive.org/release/rel-id/front",
        )

    def test_returns_empty_when_no_sources(self) -> None:
        meta = Metadata(source="GnuDB", album_artist="A", album="B")
        self.assertEqual(primary_cover_art_url(meta), "")


class ApplyCoverArtSearchResultTests(unittest.TestCase):
    def test_copies_mb_ids_onto_target(self) -> None:
        target = Metadata(source="GnuDB", album_artist="Artist", album="Album")
        hit = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            mb_release_id="rel-id",
            mb_release_group_id="rg-id",
        )
        applied = apply_cover_art_search_result(target, hit)
        self.assertTrue(applied)
        self.assertEqual(target.mb_release_id, "rel-id")
        self.assertEqual(target.mb_release_group_id, "rg-id")
        # Source/title/etc. on the GnuDB candidate are left alone.
        self.assertEqual(target.source, "GnuDB")

    def test_copies_cover_art_url_when_target_has_none(self) -> None:
        target = Metadata(source="GnuDB", album_artist="Artist", album="Album")
        hit = Metadata(
            source="Discogs",
            album_artist="Artist",
            album="Album",
            cover_art_url="https://example.test/cover.jpg",
            cover_art_ext="jpg",
        )
        applied = apply_cover_art_search_result(target, hit)
        self.assertTrue(applied)
        self.assertEqual(target.cover_art_url, "https://example.test/cover.jpg")
        self.assertEqual(target.cover_art_ext, "jpg")

    def test_does_not_overwrite_existing_ids(self) -> None:
        target = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            mb_release_id="existing-rel",
            cover_art_url="https://example.test/existing.jpg",
        )
        hit = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            mb_release_id="other-rel",
            cover_art_url="https://example.test/other.jpg",
        )
        applied = apply_cover_art_search_result(target, hit)
        self.assertFalse(applied)
        self.assertEqual(target.mb_release_id, "existing-rel")
        self.assertEqual(target.cover_art_url, "https://example.test/existing.jpg")

    def test_returns_false_when_hit_has_no_useful_fields(self) -> None:
        target = Metadata(source="GnuDB", album_artist="Artist", album="Album")
        hit = Metadata(source="MusicBrainz", album_artist="Artist", album="Album")
        applied = apply_cover_art_search_result(target, hit)
        self.assertFalse(applied)
        self.assertEqual(target.mb_release_id, "")


class FetchCoverArtTests(unittest.TestCase):
    def test_fetch_returns_first_url_that_answers(self) -> None:
        from unittest.mock import MagicMock, patch

        from discvault.artwork import fetch_cover_art

        meta = Metadata(
            source="T",
            album_artist="A",
            album="B",
            cover_art_url="https://example.test/bad.jpg",
            mb_release_id="rid",
        )
        good = MagicMock(content=b"IMG", headers={"content-type": "image/png"})
        good.raise_for_status.return_value = None
        bad = MagicMock()
        bad.raise_for_status.side_effect = RuntimeError("404")
        with patch("discvault.artwork.requests.get", side_effect=[bad, good]) as get:
            fetched = fetch_cover_art(meta)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.content, b"IMG")
        self.assertEqual(fetched.content_type, "image/png")
        self.assertEqual(fetched.url, "https://coverartarchive.org/release/rid/front")
        self.assertEqual(get.call_count, 2)

    def test_fetch_returns_none_when_nothing_answers(self) -> None:
        from unittest.mock import patch

        from discvault.artwork import fetch_cover_art

        meta = Metadata(source="T", album_artist="A", album="B", cover_art_url="https://x.test/c.jpg")
        with patch("discvault.artwork.requests.get", side_effect=RuntimeError("down")):
            self.assertIsNone(fetch_cover_art(meta))


if __name__ == "__main__":
    unittest.main()
