"""Modal source selector for metadata providers."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label


class SourceSelectScreen(ModalScreen[dict[str, bool] | None]):
    CSS = """
    SourceSelectScreen {
        align: center middle;
        background: $background 80%;
    }

    #source-dialog {
        width: 64;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #source-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #source-list {
        height: auto;
    }

    .source-check {
        margin-bottom: 1;
    }

    #source-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #source-save {
        margin-left: 1;
    }
    """

    def __init__(self, sources: dict[str, bool]) -> None:
        super().__init__()
        self._sources = dict(sources)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Search Metadata", id="source-title"),
            Vertical(
                Checkbox("CD-Text (from disc)", value=self._sources.get("cdtext", True), id="src-cdtext", compact=True, classes="source-check"),
                Checkbox("MusicBrainz", value=self._sources.get("musicbrainz", True), id="src-musicbrainz", compact=True, classes="source-check"),
                Checkbox("GnuDB", value=self._sources.get("gnudb", False), id="src-gnudb", compact=True, classes="source-check"),
                Checkbox("Discogs", value=self._sources.get("discogs", False), id="src-discogs", compact=True, classes="source-check"),
                id="source-list",
            ),
            Horizontal(
                Button("Cancel", id="source-cancel"),
                Button("Search", id="source-save", variant="success"),
                id="source-buttons",
            ),
            id="source-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#src-cdtext", Checkbox).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "source-cancel":
            self.dismiss(None)
            return
        if event.button.id == "source-save":
            self.dismiss(self._selected_sources())

    def _selected_sources(self) -> dict[str, bool]:
        return {
            "cdtext": self.query_one("#src-cdtext", Checkbox).value,
            "musicbrainz": self.query_one("#src-musicbrainz", Checkbox).value,
            "gnudb": self.query_one("#src-gnudb", Checkbox).value,
            "discogs": self.query_one("#src-discogs", Checkbox).value,
        }
