from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from discvault.metadata.musicbrainz import _parse_response, search_releases
from discvault.metadata.types import DiscInfo


class MusicBrainzTests(unittest.TestCase):
    def _response(self, payload: dict) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    def test_ambiguous_toc_multi_disc_release_is_skipped(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=10, mb_toc="1 10 100 1")
        data = {
            "releases": [
                {
                    "title": "Album",
                    "artist-credit": [{"name": "Artist"}],
                    "media": [
                        {"track-count": 10, "tracks": [{"number": "1", "title": "Disc 1"}]},
                        {"track-count": 10, "tracks": [{"number": "1", "title": "Disc 2"}]},
                    ],
                }
            ]
        }

        results = _parse_response(data, disc_info, debug=False)

        self.assertEqual(results, [])

    def test_unique_track_count_match_is_used_for_toc_fallback(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=11, mb_toc="1 11 100 1")
        data = {
            "releases": [
                {
                    "title": "Album",
                    "artist-credit": [{"name": "Artist"}],
                    "media": [
                        {"track-count": 10, "tracks": [{"number": "1", "title": "Wrong"}]},
                        {"track-count": 11, "tracks": [{"number": "1", "title": "Right"}]},
                    ],
                }
            ]
        }

        results = _parse_response(data, disc_info, debug=False)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].tracks[0].title, "Right")
        self.assertEqual(results[0].match_quality, "toc")

    def test_ambiguous_toc_matches_across_distinct_releases_are_skipped(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=11, mb_toc="1 11 100 1")
        data = {
            "releases": [
                {
                    "title": "Album One",
                    "artist-credit": [{"name": "Artist One"}],
                    "media": [
                        {"track-count": 11, "tracks": [{"number": "1", "title": "Track"}]},
                    ],
                },
                {
                    "title": "Album Two",
                    "artist-credit": [{"name": "Artist Two"}],
                    "media": [
                        {"track-count": 11, "tracks": [{"number": "1", "title": "Track"}]},
                    ],
                },
            ]
        }

        results = _parse_response(data, disc_info, debug=False)

        self.assertEqual(results, [])

    def test_toc_matches_from_same_release_group_are_kept(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_toc="1 8 100 1")
        data = {
            "releases": [
                {
                    "id": "release-1",
                    "title": "[Album]",
                    "artist-credit": [{"name": "Artist"}],
                    "release-group": {"id": "group-1", "title": "[Album]"},
                    "media": [
                        {"track-count": 8, "tracks": [{"number": "1", "title": "Track"}]},
                    ],
                },
                {
                    "id": "release-2",
                    "title": "Album",
                    "artist-credit": [{"name": "Artist"}],
                    "release-group": {"id": "group-1", "title": "[Album]"},
                    "media": [
                        {"track-count": 8, "tracks": [{"number": "1", "title": "Track"}]},
                    ],
                },
            ]
        }

        results = _parse_response(data, disc_info, debug=False)

        self.assertEqual(len(results), 2)
        self.assertEqual({result.mb_release_group_id for result in results}, {"group-1"})
        self.assertEqual({result.album for result in results}, {"[Album]", "Album"})

    def test_toc_matches_prefer_disc_id_backed_and_more_specific_release_dates(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_toc="1 8 100 1")
        data = {
            "releases": [
                {
                    "id": "release-generic",
                    "title": "Album",
                    "date": "2012-06",
                    "artist-credit": [{"name": "Artist"}],
                    "release-group": {"id": "group-1", "title": "Album"},
                    "media": [
                        {
                            "track-count": 8,
                            "tracks": [{"number": "1", "title": "Track"}],
                            "discs": [],
                        }
                    ],
                },
                {
                    "id": "release-specific",
                    "title": "Album",
                    "date": "1994-07-01",
                    "artist-credit": [{"name": "Artist"}],
                    "release-group": {"id": "group-1", "title": "Album"},
                    "media": [
                        {
                            "track-count": 8,
                            "tracks": [{"number": "1", "title": "Track"}],
                            "discs": [{"id": "disc-id-1"}],
                        }
                    ],
                },
            ]
        }

        results = _parse_response(data, disc_info, debug=False)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].mb_release_id, "release-specific")
        self.assertEqual(results[1].mb_release_id, "release-generic")

    def test_manual_release_search_fetches_release_details(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=1)
        search_payload = {"releases": [{"id": "release-1"}]}
        detail_payload = {
            "id": "release-1",
            "title": "Album",
            "date": "2000-01-01",
            "artist-credit": [{"name": "Artist"}],
            "release-group": {"id": "group-1"},
            "media": [
                {
                    "track-count": 1,
                    "tracks": [{"number": "1", "title": "Track One"}],
                }
            ],
        }

        with patch(
            "discvault.metadata.musicbrainz.requests.get",
            side_effect=[self._response(search_payload), self._response(detail_payload)],
        ) as get:
            results = search_releases(
                "Artist",
                "Album",
                year="2000",
                disc_info=disc_info,
                debug=False,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].album_artist, "Artist")
        self.assertEqual(results[0].album, "Album")
        self.assertEqual(results[0].year, "2000")
        self.assertEqual(results[0].tracks[0].title, "Track One")
        self.assertIn("artist:(Artist)", get.call_args_list[0].kwargs["params"]["query"])
        self.assertIn("release:(Album)", get.call_args_list[0].kwargs["params"]["query"])
        self.assertIn("date:2000*", get.call_args_list[0].kwargs["params"]["query"])

    def test_free_form_release_search_uses_tokenized_query(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=1)
        search_payload = {"releases": [{"id": "release-1"}]}
        detail_payload = {
            "id": "release-1",
            "title": "Salvammo 'o munno",
            "artist-credit": [{"name": "Enzo Avitabile"}, {"name": " & "}, {"name": "Bottari"}],
            "media": [
                {
                    "track-count": 1,
                    "tracks": [{"number": "1", "title": "Track One"}],
                }
            ],
        }

        with patch(
            "discvault.metadata.musicbrainz.requests.get",
            side_effect=[self._response(search_payload), self._response(detail_payload)],
        ) as get:
            results = search_releases(
                "",
                "",
                query="Enzo Avitabile & Bottari Salvammo 'o munno",
                disc_info=disc_info,
                debug=False,
            )

        self.assertEqual(len(results), 1)
        query = get.call_args_list[0].kwargs["params"]["query"]
        self.assertIn("Enzo", query)
        self.assertIn("Avitabile", query)
        self.assertIn("Bottari", query)
        self.assertIn("Salvammo", query)
        self.assertIn("munno", query)
        self.assertNotIn(" o ", query)


class FirstReleaseYearTests(unittest.TestCase):
    def test_release_to_candidate_picks_up_first_release_date(self) -> None:
        from discvault.metadata.musicbrainz import _release_to_candidate

        disc_info = DiscInfo(device="/dev/cdrom", track_count=1)
        release = {
            "id": "release-1",
            "title": "Willy and the Poor Boys",
            "date": "2006-09-25",
            "artist-credit": [{"name": "Creedence Clearwater Revival"}],
            "release-group": {"id": "group-1", "first-release-date": "1969-11"},
            "media": [
                {"track-count": 1, "tracks": [{"number": "1", "title": "Down on the Corner"}]}
            ],
        }
        result = _release_to_candidate(release, disc_info, debug=False, match_quality="disc_id")
        self.assertIsNotNone(result)
        meta, _ = result  # type: ignore[misc]
        self.assertEqual(meta.year, "2006")
        self.assertEqual(meta.first_release_year, "1969")

    def test_release_to_candidate_leaves_first_release_year_empty_when_missing(self) -> None:
        from discvault.metadata.musicbrainz import _release_to_candidate

        disc_info = DiscInfo(device="/dev/cdrom", track_count=1)
        release = {
            "id": "release-1",
            "title": "Album",
            "date": "1969",
            "artist-credit": [{"name": "Artist"}],
            "release-group": {"id": "group-1"},
            "media": [
                {"track-count": 1, "tracks": [{"number": "1", "title": "One"}]}
            ],
        }
        result = _release_to_candidate(release, disc_info, debug=False, match_quality="disc_id")
        self.assertIsNotNone(result)
        meta, _ = result  # type: ignore[misc]
        self.assertEqual(meta.year, "1969")
        self.assertEqual(meta.first_release_year, "")


if __name__ == "__main__":
    unittest.main()
