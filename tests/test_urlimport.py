from __future__ import annotations

import unittest
from unittest.mock import patch

from discvault.metadata import urlimport
from discvault.metadata.types import DiscInfo, Metadata


class UrlImportTests(unittest.TestCase):
    def test_provider_name_detects_bandcamp(self) -> None:
        self.assertEqual(
            urlimport.provider_name("https://artist.bandcamp.com/album/test"),
            "Bandcamp",
        )

    def test_lookup_url_routes_to_bandcamp(self) -> None:
        disc_info = DiscInfo(device="/dev/cdrom")
        meta = Metadata(source="Bandcamp", album_artist="Artist", album="Album")

        with patch(
            "discvault.metadata.urlimport.bandcamp.lookup_url",
            return_value=[meta],
        ) as lookup:
            results = urlimport.lookup_url(
                "https://artist.bandcamp.com/album/test",
                disc_info=disc_info,
            )

        self.assertEqual(results, [meta])
        lookup.assert_called_once()

    def test_lookup_url_rejects_unsupported_hosts(self) -> None:
        with self.assertRaises(ValueError):
            urlimport.lookup_url("https://example.com/album/test")


if __name__ == "__main__":
    unittest.main()
