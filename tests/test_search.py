from __future__ import annotations

import unittest

from discvault.metadata.search import combine_search_text, extract_year, search_tokens


class MetadataSearchHelpersTests(unittest.TestCase):
    def test_combine_search_text_prefers_explicit_query(self) -> None:
        self.assertEqual(
            combine_search_text(
                "Enzo Avitabile Salvammo o munno",
                artist="Ignored Artist",
                album="Ignored Album",
                year="2001",
            ),
            "Enzo Avitabile Salvammo o munno",
        )

    def test_combine_search_text_falls_back_to_structured_fields(self) -> None:
        self.assertEqual(
            combine_search_text("", artist="Artist", album="Album", year="2000"),
            "Artist Album 2000",
        )

    def test_search_tokens_deduplicate_and_drop_single_letter_noise(self) -> None:
        self.assertEqual(
            search_tokens("Salvammo 'o munno Salvammo 2004"),
            ["Salvammo", "munno", "2004"],
        )

    def test_extract_year_returns_first_year(self) -> None:
        self.assertEqual(extract_year("Album title 2004 remaster"), "2004")


if __name__ == "__main__":
    unittest.main()
