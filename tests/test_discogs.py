from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from discvault.metadata.discogs import lookup
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


if __name__ == "__main__":
    unittest.main()
