"""Modal cover-art viewer: shows an image inside the TUI.

Rendering is chosen at runtime, best first:

1. ``textual-image`` (optional ``images`` extra) — Kitty/Sixel graphics where the
   terminal supports them, its own character fallbacks elsewhere.
2. Pillow half-block rendering — works in any truecolor terminal.
3. Neither installed: the caller never opens this screen and uses the system
   opener instead (``cover_render.viewer_available``).

The image is fetched in a worker thread so the UI never blocks on the network.
"""
from __future__ import annotations

import io
from collections.abc import Callable

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from .cover_render import halfblock_text, textual_image_available

# Result a caller can act on: the user asked for the system viewer instead.
OPEN_EXTERNALLY = "external"


class CoverViewerScreen(ModalScreen[str | None]):
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("o", "external", "Open externally"),
    ]

    CSS = """
    CoverViewerScreen {
        align: center middle;
        background: $background 80%;
    }

    #cover-dialog {
        width: 100%;
        height: 100%;
        border: round $surface;
        background: $panel;
        padding: 0 1;
    }

    #cover-title {
        text-style: bold;
        height: 1;
    }

    #cover-body {
        height: 1fr;
        content-align: center middle;
        text-align: center;
    }

    #cover-hint {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, *, title: str, fetch: Callable[[], bytes | None]) -> None:
        """``fetch`` runs in a worker thread and returns image bytes, or None."""
        super().__init__()
        self._title = title
        self._fetch = fetch
        self._data: bytes | None = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="cover-title"),
            Static("Loading cover art…", id="cover-body"),
            Label("Esc/q close · o open in external viewer", id="cover-hint"),
            id="cover-dialog",
        )

    def on_mount(self) -> None:
        self._load()

    @work(thread=True, name="cover-view-fetch", exclusive=True)
    def _load(self) -> None:
        try:
            data = self._fetch()
        except Exception:
            data = None
        self.app.call_from_thread(self._show, data)

    def _show(self, data: bytes | None) -> None:
        body = self.query_one("#cover-body", Static)
        if not data:
            body.update("Could not download the cover art.")
            return
        self._data = data
        if textual_image_available() and self._show_with_textual_image(data):
            return
        self._show_halfblocks(body, data)

    def _show_with_textual_image(self, data: bytes) -> bool:
        """Swap the placeholder for a textual-image widget; False if it fails."""
        try:
            from PIL import Image as PILImage
            from .cover_render import _textual_image_widget

            widget = _textual_image_widget.Image(PILImage.open(io.BytesIO(data)), id="cover-image")
            widget.styles.width = "100%"
            widget.styles.height = "1fr"
            # Hide rather than remove the placeholder: removal is asynchronous,
            # and the new widget must not share its id while both exist.
            self.query_one("#cover-body").display = False
            self.query_one("#cover-dialog").mount(widget, before="#cover-hint")
            return True
        except Exception:
            return False

    def _show_halfblocks(self, body: Static, data: bytes) -> None:
        size = body.size
        try:
            body.update(halfblock_text(data, size.width, size.height))
        except (ValueError, RuntimeError) as exc:
            body.update(f"Cannot display this image: {exc}")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_external(self) -> None:
        self.dismiss(OPEN_EXTERNALLY)
