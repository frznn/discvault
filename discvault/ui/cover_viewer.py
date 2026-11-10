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

from .cover_render import halfblock_text, low_resolution_renderer, textual_image_available

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
        width: auto;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 0 1;
    }

    #cover-title {
        text-style: bold;
        height: 1;
    }

    #cover-body {
        /* Sized in cells by _apply_box so the picture area is square. */
        width: 40;
        height: 20;
        content-align: center middle;
        text-align: center;
    }

    #cover-hint {
        height: auto;
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
            Label(self._hint(), id="cover-hint"),
            id="cover-dialog",
        )

    @staticmethod
    def _hint() -> str:
        keys = "Esc/q close · o open in external viewer"
        if low_resolution_renderer():
            return f"Low resolution: no image protocol in this terminal. o opens the full-quality external viewer · Esc/q close"
        return keys

    # Cells are about twice as tall as wide, so a square picture is twice
    # as many columns as rows. The dialog chrome around it: a 2-row border,
    # a title row and up to three hint rows; a 2-column border and padding.
    _CHROME_ROWS = 6
    # Upper bound on the picture's height in rows (so 2x that in columns):
    # a preview, not a full-screen view. The external viewer is for detail.
    _MAX_ROWS = 16
    _CHROME_COLS = 4

    def on_mount(self) -> None:
        self._apply_box()
        self._load()

    def on_resize(self) -> None:
        self._apply_box()
        if self._data is not None and not self.query("#cover-image"):
            self._show_halfblocks(self.query_one("#cover-body", Static), self._data)

    def _apply_box(self) -> None:
        """Size the picture area to the largest square that fits the screen."""
        rows = min(
            self._MAX_ROWS,
            self.size.height - self._CHROME_ROWS,
            (self.size.width - self._CHROME_COLS) // 2,
        )
        rows = max(4, rows)
        # An explicit dialog width keeps the long hint line wrapping inside it.
        self.query_one("#cover-dialog").styles.width = rows * 2 + self._CHROME_COLS
        for widget in (self.query_one("#cover-body"), *self.query("#cover-image")):
            widget.styles.width = rows * 2
            widget.styles.height = rows

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
            # Hide rather than remove the placeholder: removal is asynchronous,
            # and the new widget must not share its id while both exist.
            self.query_one("#cover-body").display = False
            self.query_one("#cover-dialog").mount(widget, before="#cover-hint")
            self._apply_box()
            return True
        except Exception:
            return False

    def _show_halfblocks(self, body: Static, data: bytes) -> None:
        # Read the box from its styles: after a resize the laid-out size lags.
        cols = int(body.styles.width.value) if body.styles.width else body.size.width
        rows = int(body.styles.height.value) if body.styles.height else body.size.height
        try:
            body.update(halfblock_text(data, cols, rows))
        except (ValueError, RuntimeError) as exc:
            body.update(f"Cannot display this image: {exc}")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_external(self) -> None:
        self.dismiss(OPEN_EXTERNALLY)
