from __future__ import annotations

import unittest
from unittest.mock import patch

from discvault.config import Config
from discvault.metadata.lookup import LookupCallbacks, fetch_candidates
from discvault.metadata.types import DiscInfo


class LookupTests(unittest.TestCase):
    def test_automatic_lookup_ignores_manual_search_terms(self) -> None:
        cfg = Config()
        cfg.discogs.token = "token"
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_disc_id="disc-id")

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as lookup_release, \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup:
            fetch_candidates(
                disc_info,
                cfg,
                sources={
                    "cdtext": False,
                    "musicbrainz": True,
                    "gnudb": False,
                },
                manual_query="Artist Album",
                manual_hints=("Artist", "Album", ""),
            )

        lookup_release.assert_called_once()
        search_releases.assert_not_called()
        discogs_lookup.assert_not_called()

    def test_manual_search_uses_discogs_without_token_and_skips_auto_lookup(self) -> None:
        cfg = Config()
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_disc_id="disc-id")
        manual_disc_info = DiscInfo(device="/dev/cdrom", track_count=7)
        notices: list[str] = []

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as lookup_release, \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup:
            fetch_candidates(
                disc_info,
                cfg,
                sources={
                    "cdtext": True,
                    "musicbrainz": True,
                    "gnudb": True,
                },
                manual_query="Artist Album",
                manual_search=True,
                manual_search_disc_info=manual_disc_info,
                callbacks=LookupCallbacks(on_info=notices.append),
            )

        lookup_release.assert_not_called()
        search_releases.assert_called_once()
        self.assertEqual(search_releases.call_args.kwargs["disc_info"], manual_disc_info)
        discogs_lookup.assert_called_once()
        self.assertEqual(discogs_lookup.call_args.args[0], manual_disc_info)
        self.assertIn("Discogs: using anonymous access", notices[0])


    def test_source_order_drives_provider_sequence(self) -> None:
        cfg = Config()
        cfg.gnudb.host = "gnudb.example"
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        def record(label: str) -> None:
            events.append(label)

        with patch("discvault.metadata.cdtext.lookup", return_value=[]), \
            patch("discvault.metadata.local.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch("discvault.metadata.gnudb.lookup_http", return_value=[]), \
            patch("discvault.metadata.gnudb.lookup_cddbp", return_value=[]):
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["gnudb", "cdtext", "musicbrainz"],
                callbacks=LookupCallbacks(on_start=record),
            )

        priority_events = [e for e in events if e not in {"Local CDDB cache"}]
        self.assertEqual(
            priority_events,
            ["GnuDB HTTP", "GnuDB CDDBP (gnudb.example)", "CD-Text", "MusicBrainz"],
        )
        self.assertEqual(events[0], "Local CDDB cache")

    def test_source_order_falls_back_to_cfg_when_not_passed(self) -> None:
        cfg = Config()
        cfg.metadata_source_order = ["musicbrainz", "cdtext", "gnudb"]
        cfg.use_local_cddb_cache = False
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        with patch("discvault.metadata.cdtext.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch("discvault.metadata.gnudb.lookup_http", return_value=[]):
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["MusicBrainz", "CD-Text", "GnuDB HTTP"])


if __name__ == "__main__":
    unittest.main()
