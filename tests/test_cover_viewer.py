from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from textual.app import App

from discvault.ui import cover_viewer
from discvault.ui.cover_render import pillow_available, textual_image_available
from discvault.ui.cover_viewer import OPEN_EXTERNALLY, CoverViewerScreen


def _png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


class _Host(App):
    """Minimal app that shows the viewer and records how it was dismissed."""

    def __init__(self, fetch) -> None:
        super().__init__()
        self._fetch = fetch
        self.result: object = "unset"

    def on_mount(self) -> None:
        self.push_screen(
            CoverViewerScreen(title="Artist — Album", fetch=self._fetch),
            lambda r: setattr(self, "result", r),
        )


@unittest.skipUnless(pillow_available(), "Pillow not installed")
class CoverViewerScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_halfblock_renderer_fills_body(self) -> None:
        data = _png()
        app = _Host(lambda: data)
        with patch.object(cover_viewer, "textual_image_available", lambda: False):
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause(0.5)
                body = app.screen.query_one("#cover-body")
                self.assertIn("▀", body.content.plain)
                self.assertEqual(len(app.screen.query("#cover-image")), 0)

    @unittest.skipUnless(textual_image_available(), "textual-image not installed")
    async def test_textual_image_renderer_mounts_image_widget(self) -> None:
        data = _png()
        app = _Host(lambda: data)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause(0.5)
            self.assertEqual(len(app.screen.query("#cover-image")), 1)
            self.assertFalse(app.screen.query_one("#cover-body").display)

    async def test_low_resolution_renderer_shows_warning(self) -> None:
        app = _Host(lambda: None)
        with patch.object(cover_viewer, "low_resolution_renderer", lambda: True):
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause(0.3)
                hint = app.screen.query_one("#cover-hint")
                self.assertIn("Low resolution", str(hint.content))

    async def test_failed_download_shows_message(self) -> None:
        app = _Host(lambda: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause(0.5)
            body = app.screen.query_one("#cover-body")
            self.assertIn("Could not download", str(body.content))

    async def test_escape_closes_with_none(self) -> None:
        app = _Host(lambda: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("escape")
            await pilot.pause(0.2)
        self.assertIsNone(app.result)

    async def test_o_requests_external_viewer(self) -> None:
        app = _Host(lambda: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("o")
            await pilot.pause(0.2)
        self.assertEqual(app.result, OPEN_EXTERNALLY)


if __name__ == "__main__":
    unittest.main()
