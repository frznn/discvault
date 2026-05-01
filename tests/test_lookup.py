from __future__ import annotations

import unittest
from unittest.mock import patch

from discvault.config import Config
from discvault.metadata.lookup import (
    LookupCallbacks,
    _blank_redundant_track_artists,
    _metadata_equivalent,
    fetch_candidates,
)
from discvault.metadata.types import DiscInfo, Metadata, Track


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


    def test_manual_search_skips_discogs_when_toggle_off(self) -> None:
        cfg = Config()
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_disc_id="disc-id")
        skips: list[tuple[str, str]] = []

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup:
            fetch_candidates(
                disc_info,
                cfg,
                sources={"musicbrainz": True, "discogs": False},
                manual_query="Artist Album",
                manual_hints=("Artist", "Album", ""),
                manual_search=True,
                callbacks=LookupCallbacks(on_skip=lambda label, reason: skips.append((label, reason))),
            )

        search_releases.assert_called_once()
        discogs_lookup.assert_not_called()
        self.assertIn(("Discogs", "disabled in Manual Search"), skips)

    def test_manual_search_skips_musicbrainz_when_toggle_off(self) -> None:
        cfg = Config()
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_disc_id="disc-id")

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup:
            fetch_candidates(
                disc_info,
                cfg,
                sources={"musicbrainz": False, "discogs": True},
                manual_query="Artist Album",
                manual_hints=("Artist", "Album", ""),
                manual_search=True,
            )

        search_releases.assert_not_called()
        discogs_lookup.assert_called_once()

    def test_provider_duration_is_reported_via_on_success(self) -> None:
        cfg = Config()
        cfg.use_local_cddb_cache = False
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[tuple[str, int, float]] = []

        with patch(
            "discvault.metadata.cdtext.lookup",
            return_value=[Metadata(source="CD-Text", album_artist="X", album="A")],
        ), patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch("discvault.metadata.gnudb.lookup_http", return_value=[]):
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["cdtext", "musicbrainz", "gnudb"],
                callbacks=LookupCallbacks(
                    on_success=lambda label, count, duration: events.append((label, count, duration))
                ),
            )

        self.assertTrue(events)
        for label, _, duration in events:
            self.assertGreaterEqual(duration, 0.0, f"duration for {label} should be non-negative")

    def test_short_circuit_stops_priority_loop_on_first_match(self) -> None:
        cfg = Config()
        cfg.use_local_cddb_cache = False
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        with patch(
            "discvault.metadata.cdtext.lookup",
            return_value=[Metadata(source="CD-Text", album_artist="X", album="A")],
        ), patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as mb, \
            patch("discvault.metadata.gnudb.lookup_http", return_value=[]) as gnudb_http:
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["cdtext", "musicbrainz", "gnudb"],
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["CD-Text"])
        mb.assert_not_called()
        gnudb_http.assert_not_called()

    def test_short_circuit_disabled_collects_from_every_source(self) -> None:
        cfg = Config()
        cfg.use_local_cddb_cache = False
        cfg.lookup_stop_at_first_match = False
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        with patch(
            "discvault.metadata.cdtext.lookup",
            return_value=[Metadata(source="CD-Text", album_artist="X", album="A")],
        ), patch(
            "discvault.metadata.musicbrainz.lookup",
            return_value=[Metadata(source="MusicBrainz", album_artist="X", album="B")],
        ), patch("discvault.metadata.gnudb.lookup_http", return_value=[]):
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["cdtext", "musicbrainz", "gnudb"],
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["CD-Text", "MusicBrainz", "GnuDB HTTP"])

    def test_short_circuit_walks_past_empty_providers(self) -> None:
        cfg = Config()
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
            patch(
                "discvault.metadata.gnudb.lookup_http",
                return_value=[Metadata(source="GnuDB", album_artist="X", album="C")],
            ):
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["cdtext", "musicbrainz", "gnudb"],
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["CD-Text", "MusicBrainz", "GnuDB HTTP"])

    def test_short_circuit_cache_hit_skips_priority_loop(self) -> None:
        cfg = Config()
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        with patch(
            "discvault.metadata.local.lookup",
            return_value=[Metadata(source="Local", album_artist="X", album="D")],
        ), patch("discvault.metadata.cdtext.lookup", return_value=[]) as cdtext_lookup, \
            patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as mb_lookup, \
            patch("discvault.metadata.gnudb.lookup_http", return_value=[]) as gnudb_http:
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["Local CDDB cache"])
        cdtext_lookup.assert_not_called()
        mb_lookup.assert_not_called()
        gnudb_http.assert_not_called()

    def test_short_circuit_gnudb_http_hit_skips_cddbp(self) -> None:
        cfg = Config()
        cfg.use_local_cddb_cache = False
        cfg.gnudb.host = "gnudb.example"
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=8,
            mb_disc_id="disc-id",
            freedb_disc_id="12345678",
        )

        events: list[str] = []

        with patch("discvault.metadata.cdtext.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch(
                "discvault.metadata.gnudb.lookup_http",
                return_value=[Metadata(source="GnuDB", album_artist="X", album="E")],
            ), patch("discvault.metadata.gnudb.lookup_cddbp", return_value=[]) as cddbp:
            fetch_candidates(
                disc_info,
                cfg,
                sources={"cdtext": True, "musicbrainz": True, "gnudb": True},
                source_order=["gnudb", "cdtext", "musicbrainz"],
                callbacks=LookupCallbacks(on_start=events.append),
            )

        self.assertEqual(events, ["GnuDB HTTP"])
        cddbp.assert_not_called()


class BlankRedundantTrackArtistsTests(unittest.TestCase):
    def _meta(self, album_artist: str, *track_artists: str) -> Metadata:
        return Metadata(
            source="Test",
            album_artist=album_artist,
            album="Album",
            tracks=[
                Track(number=i + 1, title=f"T{i+1}", artist=a)
                for i, a in enumerate(track_artists)
            ],
        )

    def test_single_artist_disc_is_blanked(self) -> None:
        meta = self._meta("Artist", "Artist", "Artist", "Artist")
        _blank_redundant_track_artists(meta)
        self.assertEqual([t.artist for t in meta.tracks], ["", "", ""])

    def test_empty_per_track_artist_counts_as_matching(self) -> None:
        meta = self._meta("Artist", "Artist", "", "Artist")
        _blank_redundant_track_artists(meta)
        self.assertEqual([t.artist for t in meta.tracks], ["", "", ""])

    def test_compilation_is_left_untouched(self) -> None:
        meta = self._meta("Various Artists", "Beatles", "Stones", "Beatles")
        before = [t.artist for t in meta.tracks]
        _blank_redundant_track_artists(meta)
        self.assertEqual([t.artist for t in meta.tracks], before)

    def test_one_differing_track_keeps_all(self) -> None:
        meta = self._meta("Artist", "Artist", "Artist", "Guest")
        before = [t.artist for t in meta.tracks]
        _blank_redundant_track_artists(meta)
        self.assertEqual([t.artist for t in meta.tracks], before)

    def test_empty_album_artist_is_noop(self) -> None:
        meta = self._meta("", "Artist", "Artist")
        _blank_redundant_track_artists(meta)
        self.assertEqual([t.artist for t in meta.tracks], ["Artist", "Artist"])


class MetadataEquivalentTests(unittest.TestCase):
    def _meta(self, **overrides) -> Metadata:
        base = dict(
            source="X",
            album_artist="Artist",
            album="Album",
            year="2010",
            tracks=[Track(number=1, title="One"), Track(number=2, title="Two")],
        )
        base.update(overrides)
        return Metadata(**base)

    def test_same_content_different_source_is_equivalent(self) -> None:
        a = self._meta(source="GnuDB", match_quality="disc_id")
        b = self._meta(source="GnuDB-CDDBP", match_quality="disc_id")
        self.assertTrue(_metadata_equivalent(a, b))

    def test_match_quality_difference_is_ignored(self) -> None:
        a = self._meta(source="MusicBrainz", match_quality="disc_id")
        b = self._meta(source="MusicBrainz", match_quality="toc")
        self.assertTrue(_metadata_equivalent(a, b))

    def test_album_difference_breaks_equivalence(self) -> None:
        a = self._meta(album="Album")
        b = self._meta(album="Album (Remastered)")
        self.assertFalse(_metadata_equivalent(a, b))

    def test_track_difference_breaks_equivalence(self) -> None:
        a = self._meta()
        b = self._meta(tracks=[Track(number=1, title="One"), Track(number=2, title="Different")])
        self.assertFalse(_metadata_equivalent(a, b))

    def test_identifier_field_difference_breaks_equivalence(self) -> None:
        a = self._meta(mb_release_id="aaa")
        b = self._meta(mb_release_id="bbb")
        self.assertFalse(_metadata_equivalent(a, b))

    def test_discogs_release_id_difference_breaks_equivalence(self) -> None:
        a = self._meta(discogs_release_id=1)
        b = self._meta(discogs_release_id=2)
        self.assertFalse(_metadata_equivalent(a, b))


class DedupeEquivalentCandidatesConfigTests(unittest.TestCase):
    def _disc_info(self) -> DiscInfo:
        return DiscInfo(device="/dev/cdrom", track_count=2, freedb_disc_id="abcdef01", mb_disc_id="disc-id")

    def _gnudb_record(self, source: str) -> Metadata:
        return Metadata(
            source=source,
            album_artist="Creedence Clearwater Revival",
            album="Green River",
            year="1969",
            tracks=[Track(number=1, title="Green River"), Track(number=2, title="Commotion")],
        )

    def test_dedupe_on_drops_equivalent_gnudb_records(self) -> None:
        cfg = Config()
        cfg.dedupe_equivalent_candidates = True
        cfg.lookup_stop_at_first_match = False
        cfg.gnudb.host = "gnudb.gnudb.org"
        with patch(
            "discvault.metadata.gnudb.lookup_http",
            return_value=[self._gnudb_record("GnuDB")],
        ), patch(
            "discvault.metadata.gnudb.lookup_cddbp",
            return_value=[self._gnudb_record("GnuDB-CDDBP")],
        ):
            results = fetch_candidates(
                self._disc_info(),
                cfg,
                sources={"cdtext": False, "musicbrainz": False, "gnudb": True},
                source_order=["gnudb"],
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "GnuDB")

    def test_dedupe_off_keeps_both_protocol_records(self) -> None:
        cfg = Config()
        cfg.dedupe_equivalent_candidates = False
        cfg.lookup_stop_at_first_match = False
        cfg.gnudb.host = "gnudb.gnudb.org"
        with patch(
            "discvault.metadata.gnudb.lookup_http",
            return_value=[self._gnudb_record("GnuDB")],
        ), patch(
            "discvault.metadata.gnudb.lookup_cddbp",
            return_value=[self._gnudb_record("GnuDB-CDDBP")],
        ):
            results = fetch_candidates(
                self._disc_info(),
                cfg,
                sources={"cdtext": False, "musicbrainz": False, "gnudb": True},
                source_order=["gnudb"],
            )
        self.assertEqual([m.source for m in results], ["GnuDB", "GnuDB-CDDBP"])


class BlankRedundantTrackArtistsConfigTests(unittest.TestCase):
    def _make_cfg(self, *, toggle: bool) -> Config:
        cfg = Config()
        cfg.blank_redundant_track_artist = toggle
        return cfg

    def _disc_info(self) -> DiscInfo:
        return DiscInfo(device="/dev/cdrom", track_count=2, mb_disc_id="disc-id")

    def _seeded_meta(self) -> Metadata:
        return Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[
                Track(number=1, title="One", artist="Artist"),
                Track(number=2, title="Two", artist="Artist"),
            ],
        )

    def test_fetch_candidates_blanks_when_toggle_on(self) -> None:
        cfg = self._make_cfg(toggle=True)
        with patch(
            "discvault.metadata.musicbrainz.lookup",
            return_value=[self._seeded_meta()],
        ):
            results = fetch_candidates(
                self._disc_info(),
                cfg,
                sources={"cdtext": False, "musicbrainz": True, "gnudb": False},
            )
        self.assertEqual(len(results), 1)
        self.assertEqual([t.artist for t in results[0].tracks], ["", ""])

    def test_fetch_candidates_preserves_when_toggle_off(self) -> None:
        cfg = self._make_cfg(toggle=False)
        with patch(
            "discvault.metadata.musicbrainz.lookup",
            return_value=[self._seeded_meta()],
        ):
            results = fetch_candidates(
                self._disc_info(),
                cfg,
                sources={"cdtext": False, "musicbrainz": True, "gnudb": False},
            )
        self.assertEqual(len(results), 1)
        self.assertEqual([t.artist for t in results[0].tracks], ["Artist", "Artist"])


if __name__ == "__main__":
    unittest.main()
