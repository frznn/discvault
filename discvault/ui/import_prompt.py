"""Modal prompts for metadata search and import values."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class TextPromptScreen(ModalScreen[str | None]):
    CSS = """
    TextPromptScreen {
        align: center middle;
        background: $background 80%;
    }

    #text-prompt-dialog {
        width: 84;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #text-prompt-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #text-prompt-label {
        margin-bottom: 1;
        color: $text-muted;
    }

    #text-prompt-input {
        width: 1fr;
    }

    #text-prompt-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #text-prompt-submit {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        *,
        title: str,
        label: str,
        value: str,
        placeholder: str,
        submit_label: str,
    ) -> None:
        super().__init__()
        self._title = title
        self._label = label
        self._value = value
        self._placeholder = placeholder
        self._submit_label = submit_label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="text-prompt-title"),
            Label(self._label, id="text-prompt-label"),
            Input(
                value=self._value,
                placeholder=self._placeholder,
                id="text-prompt-input",
                compact=True,
            ),
            Horizontal(
                Button("Cancel", id="text-prompt-cancel"),
                Button(self._submit_label, id="text-prompt-submit", variant="success"),
                id="text-prompt-buttons",
            ),
            id="text-prompt-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#text-prompt-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "text-prompt-cancel":
            self.dismiss(None)
            return
        if event.button.id == "text-prompt-submit":
            self.dismiss(self.query_one("#text-prompt-input", Input).value.strip())

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.dismiss(self.query_one("#text-prompt-input", Input).value.strip())


class MetadataImportPromptScreen(ModalScreen[tuple[str, str] | None]):
    CSS = """
    MetadataImportPromptScreen {
        align: center middle;
        background: $background 80%;
    }

    #metadata-import-dialog {
        width: 84;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #metadata-import-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #metadata-import-label {
        margin-bottom: 1;
        color: $text-muted;
    }

    #metadata-import-mode-row {
        height: auto;
        margin-bottom: 1;
    }

    #metadata-import-mode-row Button {
        margin-right: 1;
    }

    #metadata-import-input-label {
        margin-bottom: 1;
        color: $text-muted;
    }

    #metadata-import-input {
        width: 1fr;
    }

    #metadata-import-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #metadata-import-submit {
        margin-left: 1;
    }
    """

    SUPPORTED_FILE_TYPES = (".cue", ".toc", ".json", ".toml")
    SUPPORTED_URL_SITES = ("Bandcamp", "Discogs")

    def __init__(self, *, file_value: str, url_value: str) -> None:
        super().__init__()
        self._mode_values = {
            "file": file_value,
            "url": url_value,
        }
        self._mode = "url" if url_value and not file_value else "file"

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Import Metadata", id="metadata-import-title"),
            Label(
                self._help_for_mode(self._mode),
                id="metadata-import-label",
            ),
            Horizontal(
                Button("File", id="metadata-import-mode-file"),
                Button("URL", id="metadata-import-mode-url"),
                id="metadata-import-mode-row",
            ),
            Label("Path", id="metadata-import-input-label"),
            Input(
                value=self._mode_values[self._mode],
                placeholder=self._placeholder_for_mode(self._mode),
                id="metadata-import-input",
                compact=True,
            ),
            Horizontal(
                Button("Cancel", id="metadata-import-cancel"),
                Button("Import", id="metadata-import-submit", variant="success"),
                id="metadata-import-buttons",
            ),
            id="metadata-import-dialog",
        )

    def on_mount(self) -> None:
        self._refresh_mode_buttons()
        self.query_one("#metadata-import-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "metadata-import-cancel":
            self.dismiss(None)
            return
        if button_id == "metadata-import-submit":
            self.dismiss((self._mode, self.query_one("#metadata-import-input", Input).value.strip()))
            return
        if button_id == "metadata-import-mode-file":
            self._set_mode("file")
            return
        if button_id == "metadata-import-mode-url":
            self._set_mode("url")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "metadata-import-input":
            self._mode_values[self._mode] = event.value

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.dismiss((self._mode, self.query_one("#metadata-import-input", Input).value.strip()))

    def _set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode_values[self._mode] = self.query_one("#metadata-import-input", Input).value
        self._mode = mode
        self._refresh_mode_buttons()
        self.query_one("#metadata-import-label", Label).update(self._help_for_mode(self._mode))
        input_widget = self.query_one("#metadata-import-input", Input)
        input_widget.value = self._mode_values[self._mode]
        input_widget.placeholder = self._placeholder_for_mode(self._mode)
        input_widget.focus()

    def _refresh_mode_buttons(self) -> None:
        file_button = self.query_one("#metadata-import-mode-file", Button)
        url_button = self.query_one("#metadata-import-mode-url", Button)
        file_button.variant = "primary" if self._mode == "file" else "default"
        url_button.variant = "primary" if self._mode == "url" else "default"

    def _placeholder_for_mode(self, mode: str) -> str:
        if mode == "url":
            return "https://artist.bandcamp.com/album/album-name"
        return "/path/to/album.cue"

    @classmethod
    def _help_for_mode(cls, mode: str) -> str:
        if mode == "url":
            return f"Supported sites: {', '.join(cls.SUPPORTED_URL_SITES)}"
        return f"Supported file types: {', '.join(cls.SUPPORTED_FILE_TYPES)}"
