from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from discvault.metadata import discogs
from discvault.metadata.discogs import lookup, lookup_url, _id_from_url, _release_id_from_url
from discvault.metadata.types import DiscInfo


class DiscogsTests(unittest.TestCase):
    def _response(self, payload: dict) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = payload
        return response

    def test_free_form_lookup_uses_q_search_and_keeps_inexact_track_counts(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=1)
        search_payload = {"results": [{"id": 42}]}
        detail_payload = {
            "artists": [{"name": "Enzo Avitabile & Bottari"}],
            "title": "Salvammo 'o munno",
            "year": 2004,
            "tracklist": [
                {"type_": "track", "title": "One"},
                {"type_": "track", "title": "Two"},
            ],
        }

        with patch(
            "discvault.metadata.discogs.requests.get",
            side_effect=[self._response(search_payload), self._response(detail_payload)],
        ) as get:
            results = lookup(
                disc_info,
                query="Enzo Avitabile Bottari Salvammo munno",
                debug=False,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["q"], "Enzo Avitabile Bottari Salvammo munno")
        self.assertEqual(results[0].match_quality, "search")
        self.assertEqual(results[0].track_count, 2)


class DiscogsUrlTests(unittest.TestCase):
    def test_release_id_extraction(self) -> None:
        self.assertEqual(
            _release_id_from_url("https://www.discogs.com/release/12345-Artist-Title"),
            12345,
        )
        self.assertEqual(
            _release_id_from_url("https://www.discogs.com/release/67890"),
            67890,
        )
        self.assertEqual(
            _release_id_from_url("https://www.discogs.com/en/release/12345-Slug"),
            12345,
        )
        self.assertEqual(
            _release_id_from_url("www.discogs.com/release/42-X"),
            42,
        )

    def test_release_id_rejects_non_release_urls(self) -> None:
        self.assertIsNone(_release_id_from_url(""))
        self.assertIsNone(_release_id_from_url("https://example.com/release/12345"))
        self.assertIsNone(_release_id_from_url("https://www.discogs.com/master/12345"))
        self.assertIsNone(_release_id_from_url("https://www.discogs.com/artist/Foo"))

    def test_id_from_url_recognises_master_urls(self) -> None:
        self.assertEqual(
            _id_from_url("https://www.discogs.com/master/55269-Creedence-Bayou-Country"),
            ("master", 55269),
        )
        self.assertEqual(
            _id_from_url("https://www.discogs.com/en/master/55269"),
            ("master", 55269),
        )
        self.assertEqual(
            _id_from_url("https://www.discogs.com/release/999-Slug"),
            ("release", 999),
        )
        self.assertIsNone(_id_from_url("https://www.discogs.com/artist/Foo"))
        self.assertIsNone(_id_from_url("https://example.com/master/55269"))

    def test_lookup_url_fetches_release_and_returns_metadata(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=2)
        detail_payload = {
            "artists": [{"name": "Artist"}],
            "title": "Album",
            "year": 2010,
            "tracklist": [
                {"type_": "track", "title": "One"},
                {"type_": "track", "title": "Two"},
            ],
        }

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = detail_payload

        with patch(
            "discvault.metadata.discogs.requests.get",
            return_value=response,
        ) as get:
            results = lookup_url(
                "https://www.discogs.com/release/999-Some-Title",
                disc_info=disc_info,
                token="abc",
            )

        self.assertEqual(len(results), 1)
        meta = results[0]
        self.assertEqual(meta.source, "Discogs")
        self.assertEqual(meta.album, "Album")
        self.assertEqual(meta.discogs_release_id, 999)
        self.assertEqual(meta.track_count, 2)
        get.assert_called_once()
        called_url = get.call_args.args[0]
        self.assertIn("/releases/999", called_url)
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Discogs token=abc")

    def test_lookup_url_returns_empty_for_invalid_url(self) -> None:
        with patch("discvault.metadata.discogs.requests.get") as get:
            results = lookup_url("https://www.discogs.com/artist/Foo")
        self.assertEqual(results, [])
        get.assert_not_called()

    def test_lookup_url_resolves_master_to_main_release(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom", track_count=2)
        master_payload = {"id": 55269, "main_release": 7777}
        release_payload = {
            "artists": [{"name": "Creedence Clearwater Revival"}],
            "title": "Bayou Country",
            "year": 1969,
            "tracklist": [
                {"type_": "track", "title": "Born on the Bayou"},
                {"type_": "track", "title": "Bootleg"},
            ],
        }

        master_resp = Mock()
        master_resp.raise_for_status.return_value = None
        master_resp.json.return_value = master_payload
        release_resp = Mock()
        release_resp.raise_for_status.return_value = None
        release_resp.json.return_value = release_payload

        with patch(
            "discvault.metadata.discogs.requests.get",
            side_effect=[master_resp, release_resp],
        ) as get:
            results = lookup_url(
                "https://www.discogs.com/master/55269-Creedence-Clearwater-Revival-Bayou-Country",
                disc_info=disc_info,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].discogs_release_id, 7777)
        self.assertEqual(results[0].album, "Bayou Country")
        self.assertEqual(get.call_args_list[0].args[0], f"{discogs._API_BASE}/masters/55269")
        self.assertEqual(get.call_args_list[1].args[0], f"{discogs._API_BASE}/releases/7777")

    def test_lookup_url_master_without_main_release_returns_empty(self) -> None:
        master_resp = Mock()
        master_resp.raise_for_status.return_value = None
        master_resp.json.return_value = {"id": 1, "main_release": 0}

        with patch(
            "discvault.metadata.discogs.requests.get",
            return_value=master_resp,
        ) as get:
            results = lookup_url("https://www.discogs.com/master/1")

        self.assertEqual(results, [])
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
