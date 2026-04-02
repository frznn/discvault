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


if __name__ == "__main__":
    unittest.main()
