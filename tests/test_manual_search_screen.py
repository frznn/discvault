from __future__ import annotations

import asyncio
import unittest

from textual.app import App
from textual.widgets import Button

from discvault.ui.manual_search import ManualSearchScreen


class _Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.result: dict | None = None

    def on_mount(self) -> None:
        self.push_screen(
            ManualSearchScreen(value="free", artist="Artist", album="Album", year="2000", tracks="12"),
            lambda r: setattr(self, "result", r),
        )


class ManualSearchScreenTests(unittest.TestCase):
    def test_submit_returns_prefilled_fields(self) -> None:
        async def run() -> dict | None:
            app = _Host()
            async with app.run_test() as pilot:
                await pilot.pause()
                app.screen.query_one("#manual-search-submit", Button).press()
                await pilot.pause()
            return app.result

        result = asyncio.run(run())
        self.assertEqual(
            result,
            {
                "query": "free",
                "artist": "Artist",
                "album": "Album",
                "year": "2000",
                "tracks": "12",
                "musicbrainz": True,
                "discogs": True,
                "include_diverging": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
