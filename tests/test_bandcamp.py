from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from discvault.metadata import bandcamp
from discvault.metadata.types import DiscInfo


class BandcampTests(unittest.TestCase):
    def _response(self, text: str) -> Mock:
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = text
        return response

    def test_lookup_url_parses_tralbum_metadata(self) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="Album, by Artist">
            <meta property="og:image" content="https://f4.bcbits.com/img/cover.jpg">
          </head>
          <body>
            <div
              id="pagedata"
              data-tralbum='{&quot;artist&quot;:&quot;Artist&quot;,&quot;current&quot;:{&quot;title&quot;:&quot;Album&quot;,&quot;release_date&quot;:&quot;15 Mar 2024 00:00:00 GMT&quot;},&quot;artFullsizeUrl&quot;:&quot;https://f4.bcbits.com/img/cover.jpg&quot;,&quot;trackinfo&quot;:[{&quot;track_num&quot;:1,&quot;title&quot;:&quot;One&quot;},{&quot;track_num&quot;:2,&quot;title&quot;:&quot;Two&quot;,&quot;artist&quot;:&quot;Guest&quot;}]}'>
            </div>
          </body>
        </html>
        """
        disc_info = DiscInfo(device="/dev/cdrom", track_count=2)

        with patch(
            "discvault.metadata.bandcamp.requests.get",
            return_value=self._response(html),
        ) as get:
            results = bandcamp.lookup_url(
                "https://artist.bandcamp.com/album/album",
                disc_info=disc_info,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].album_artist, "Artist")
        self.assertEqual(results[0].album, "Album")
        self.assertEqual(results[0].year, "2024")
        self.assertEqual(results[0].cover_art_url, "https://f4.bcbits.com/img/cover.jpg")
        self.assertEqual(results[0].tracks[0].title, "One")
        self.assertEqual(results[0].tracks[1].artist, "Guest")
        self.assertEqual(
            get.call_args.kwargs["headers"]["User-Agent"],
            "discvault/0.1 (+https://github.com/frznn/discvault)",
        )

    def test_lookup_url_rejects_non_bandcamp_hosts(self) -> None:
        with patch("discvault.metadata.bandcamp.requests.get") as get:
            results = bandcamp.lookup_url("https://example.com/album/test")

        self.assertEqual(results, [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
