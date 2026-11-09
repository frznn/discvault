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

    .manual-search-row {
        height: auto;
    }

    .manual-search-field {
        height: auto;
        width: 1fr;
        margin-bottom: 1;
        margin-right: 1;
    }

    .manual-search-field-label {
        color: $text-muted;
    }

    .manual-search-field Input {
        width: 1fr;
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
        artist: str = "",
        album: str = "",
        year: str = "",
        tracks: str = "",
        musicbrainz: bool = True,
        discogs: bool = True,
        include_diverging: bool = False,
    ) -> None:
        super().__init__()
        self._include_diverging = bool(include_diverging)
        self._value = value
        self._artist = artist
        self._album = album
        self._year = year
        self._tracks = tracks
        self._musicbrainz = bool(musicbrainz)
        self._discogs = bool(discogs)

    @staticmethod
    def _field(title: str, widget: Input) -> Vertical:
        """An input with its label above it."""
        return Vertical(
            Label(title, classes="manual-search-field-label"),
            widget,
            classes="manual-search-field",
        )

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Manual Search", id="manual-search-title"),
            Label(
                "Fill in any of the fields. Artist, album, year and tracks also filter the results.",
                id="manual-search-hint",
            ),
            Horizontal(
                self._field(
                    "Artist",
                    Input(value=self._artist, id="manual-search-artist", compact=True),
                ),
                self._field(
                    "Album",
                    Input(value=self._album, id="manual-search-album", compact=True),
                ),
                classes="manual-search-row",
            ),
            Horizontal(
                self._field(
                    "Year",
                    Input(value=self._year, id="manual-search-year",
                          max_length=4, type="integer", compact=True),
                ),
                self._field(
                    "Tracks",
                    Input(value=self._tracks, id="manual-search-tracks",
                          max_length=3, type="integer", compact=True),
                ),
                classes="manual-search-row",
            ),
            self._field(
                "Search words (any text)",
                Input(value=self._value, id="manual-search-input", compact=True),
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
            Checkbox(
                "Include results with diverging fields",
                value=self._include_diverging,
                id="manual-search-diverging",
                compact=True,
            ),
            Horizontal(
                Button("Cancel", id="manual-search-cancel"),
                Button("Search", id="manual-search-submit", variant="success"),
                id="manual-search-buttons",
            ),
            id="manual-search-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#manual-search-artist", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if (event.input.id or "").startswith("manual-search-"):
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
                "artist": self.query_one("#manual-search-artist", Input).value.strip(),
                "album": self.query_one("#manual-search-album", Input).value.strip(),
                "year": self.query_one("#manual-search-year", Input).value.strip(),
                "tracks": self.query_one("#manual-search-tracks", Input).value.strip(),
                "musicbrainz": mb,
                "discogs": discogs,
                "include_diverging": bool(
                    self.query_one("#manual-search-diverging", Checkbox).value
                ),
            }
        )
