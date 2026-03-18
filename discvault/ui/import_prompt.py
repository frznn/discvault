"""Simple modal prompt for metadata import values."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class ImportPromptScreen(ModalScreen[str | None]):
    CSS = """
    ImportPromptScreen {
        align: center middle;
        background: $background 80%;
    }

    #import-dialog {
        width: 84;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #import-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #import-label {
        margin-bottom: 1;
        color: $text-muted;
    }

    #import-input {
        width: 1fr;
    }

    #import-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #import-submit {
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
            Label(self._title, id="import-title"),
            Label(self._label, id="import-label"),
            Input(
                value=self._value,
                placeholder=self._placeholder,
                id="import-input",
                compact=True,
            ),
            Horizontal(
                Button("Cancel", id="import-cancel"),
                Button(self._submit_label, id="import-submit", variant="success"),
                id="import-buttons",
            ),
            id="import-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#import-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "import-cancel":
            self.dismiss(None)
            return
        if event.button.id == "import-submit":
            self.dismiss(self.query_one("#import-input", Input).value.strip())

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.dismiss(self.query_one("#import-input", Input).value.strip())
