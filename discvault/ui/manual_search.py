"""Modal dialog for Manual Search: query text plus per-source toggles."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label


class ManualSearchScreen(ModalScreen[dict | None]):
    CSS = """
    ManualSearchScreen {
        align: center middle;
        background: $background 80%;
    }

    #manual-search-dialog {
        width: 72;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #manual-search-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #manual-search-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #manual-search-input {
        width: 1fr;
        margin-bottom: 1;
    }

    #manual-search-sources-label {
        color: $text-muted;
        margin-top: 0;
        margin-bottom: 0;
    }

    #manual-search-sources {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    .manual-search-check {
        margin-right: 2;
    }

    #manual-search-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #manual-search-submit {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        *,
        value: str = "",
        musicbrainz: bool = True,
        discogs: bool = True,
    ) -> None:
        super().__init__()
        self._value = value
        self._musicbrainz = bool(musicbrainz)
        self._discogs = bool(discogs)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Manual Search", id="manual-search-title"),
            Label(
                "Search by artist, album, year, or any words.",
                id="manual-search-hint",
            ),
            Input(
                value=self._value,
                placeholder="",
                id="manual-search-input",
                compact=True,
            ),
            Label("Search sources:", id="manual-search-sources-label"),
            Horizontal(
                Checkbox(
                    "MusicBrainz",
                    value=self._musicbrainz,
                    id="manual-search-mb",
                    compact=True,
                    classes="manual-search-check",
                ),
                Checkbox(
                    "Discogs",
                    value=self._discogs,
                    id="manual-search-discogs",
                    compact=True,
                    classes="manual-search-check",
                ),
                id="manual-search-sources",
            ),
            Horizontal(
                Button("Cancel", id="manual-search-cancel"),
                Button("Search", id="manual-search-submit", variant="success"),
                id="manual-search-buttons",
            ),
            id="manual-search-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#manual-search-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "manual-search-input":
            self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "manual-search-cancel":
            self.dismiss(None)
            return
        if bid == "manual-search-submit":
            self._submit()

    def _submit(self) -> None:
        query = self.query_one("#manual-search-input", Input).value.strip()
        mb = bool(self.query_one("#manual-search-mb", Checkbox).value)
        discogs = bool(self.query_one("#manual-search-discogs", Checkbox).value)
        self.dismiss(
            {
                "query": query,
                "musicbrainz": mb,
                "discogs": discogs,
            }
        )
